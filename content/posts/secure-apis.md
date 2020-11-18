---
title: "Securing a containerized Flask API with Let's Encrypt Certificates"
date: 2020-11-18
draft: False
author: Mo Kari
summary: Using Certbot, Nginx, and Flask, each running in a Docker container spun up through Docker Compose, this post shows how to serve an API over HTTPS conveniently with Let's Encrypt certificates. Template repo available under https://github.com/MohamedKari/secure-flask-container-template.
---
_Using Certbot, Nginx, and Flask, each running in a Docker container spun up through Docker Compose, this post shows how to serve an API over HTTPS conveniently with Let's Encrypt certificates. Template repo available under_ https://github.com/MohamedKari/secure-flask-container-template.

# TL;DR
Make sure your server is reachable under your domain name and has Docker and Docker Compose installed. 

Then, to spin up a Flask container serving an API securely over HTTPS, run:
```sh
# On the remote host (e. g. via SSH)
git clone https://github.com/MohamedKari/secure-flask-container-template secure_flask && cd secure_flask
echo DOMAIN_NAME=$DOMAIN_NAME >> .env 
echo EMAIL_ADDRESS=$MAIL_ADDRESS >> .env
docker-compose -f docker-compose.initial.yml up --build # obtains the initial certificate using certbot
docker-compose up --build # runs Nginx, your app, and an auto-renewal certbot

# On your developer machine
curl https://api.example.org/square/5
```

That's it. You're serving a containerized Flask API, free to be modified to your wishes, over HTTPS. 

Let's dig into the inner workings of the setup. 

# Obtain the first certificate
## Set up DNS

Before starting with the actual setup, we need to make sure that we have a DNS name pointing the web server through an A or AAAA (or maybe even a CNAME?) record. Furthermore, let's kindly ask clients to only accept certificates issued by Let's Encrypt, the CA we'll be using, by setting the CAA record. This safeguards us as a bit in case an evil somebody manages to obtain a certificate for our domain from a different CA, thus minimizing the attack surface. 

So, let's set the following DNS records for our domain name.

NAME | TYPE | VALUE
-----|------|------
api  | A    | 123.45.67.89
api  | CAA  | 0 issue "letsencrypt.org"

## Ensure Availablity

Now, let's make sure that we can serve HTTP and HTTPS on ports 80 resp. 443 and that the server is reachable from the internet (possibly adding ports 80 and 443 to the cloud firewall's allowlist, e. g. EC2 Security Groups):

```sh
docker run -p 80:8888 -it python python -m http.server 8888
```

Accessing the `http://your-dns-name` through curl or your browser on your developer machine should show the directory listing from inside the container.

## Launch certbot
Once we have our DNS name set up correctly, we can initiate the process of obtaining the first certificate.  

So, what does a certificate authority (CA) such as Let's Encrypt actually certify and how? 

In an automated certification process, a _certificate requester_ creates a _certificate signing request_ containing the requester's public key and the domain names for which a certificate shall be issued.
Using a [_Domain Validation_ procedure](https://letsencrypt.org/de/docs/challenge-types/), the CA validates that the requester of a certificate is the owner of the domain name indicated in the certificate signing request. How does it validate that? Well, it asks the requester to prove his ownership of the domain by solving a challenge only the domain owner can solve, such as serving a file under the domain (HTTP-based Challenge) or adding DNS records for the domain (DNS-based Challenge).
Upon successful validation, the CA issues a certificate which certifies that the indicated domain name and the indicated public key belong together, The certificate is itself signed with the CA's private key. 

Let's Encrypt allows us to run the HTTP-based validation process fully automated using Certbot. 
Certbot is a [utility](https://certbot.eff.org/docs/using.html) that we run on the server routable under the DNS name. 
As [specified by the ACME protocol](https://tools.ietf.org/id/draft-barnes-acme-token-challenge-00.html), it will initiate the certification process and then - on our behalf - solve the challenge presented by Let's Encrypt. 

More concretely, what happens is the following:
- Certbot will first create a public-private key pair and then a _certificate signing request_ (CSR) which contains the domain name we want a certificate for and the public key. 
- Certbots sends the CSR to the CA, that is Let's Encrypt.
- Let's Encrypt will ask Certbot to serve a file with a specified random name, the token, e. g.`EgK8...kc`, under the `$DOMAIN_NAME/.well-known/challenge/EgK8...kc`, containing a secret. This is the challenge. Nobody except for the domain owner could serve this secret under the domain. If I tried to create a certificate for google.com, Let's Encrypt would ask me to place the secret under google.com, which I wouldn't be able to, because google.com requests get resolved by DNS to a Google-owned IP pointing to Google-owned servers on which I cannot serve anything.
- The Let's Encrypt validation server will send a GET request (or actually will send the same GET request multiple times from different locations[^dns-poisoning]) to `$DOMAIN_NAME/.well-known/challenge/EgK8...kc` and check if the challenge was thereby solved. 
- If the challenge succeeds, the CA issues a certificate and sends the certificate back to Certbot. 
- Certbot places the signed certificate inside `/home/ubuntu/data/certbot/conf/`. 

Nginx expects a certificate to be in place upon startup. 

To obtain the first certificate run the following (e. g. by SSHing into the remote machine, or setting the corresponding Docker Host environment variables and issuing the command locally):

```sh
docker-compose -f docker-compose.initial.yml up --build
```

This will build a trivially extended certbot image and run certbot it with the following parameters.
```sh
certbot certonly \
        --standalone \
        -d $DOMAIN_NAME \
        -m $EMAIL_ADDRESS \
        --rsa-key-size "2048" \
        --agree-tos \
        -n
        # --force-renewal
        # -vvv
```

## Check result

After finishing successfully, Certbot will have placed the created private key and public key as well as the issued certificate in the file system, mounted on the host machine:
```txt
/home/ubuntu/data/certbot/conf
├── accounts
├── archive
├── csr
├── keys
├── live
├── renewal
└── renewal-hooks
```


# Deploy and serve the application with auto-renewing certificates

## Launch the Flask application

Now, that we have our first certficate in place, let's build the app. 

Let's implement a Flask-ed python application depending on the `flask` and `waitress` package using the following scaffold:
```py
import waitress
from flask import Flask, Response, request, app, make_response
import os

app = Flask(__name__)

@app.route("/square/<int:base>", methods=["GET"])
def square(base): # pylint: disable=unused-variable
    square_product = base * base

    resp = Response(str(square_product), status=200)
    resp.headers["Access-Control-Allow-Origin"] = "*" # enables CORS for JS Fetch requests

    return resp

@app.route("/health", methods=["GET"])
def health(): 
    return make_response("", 200)


waitress.serve(app, host="0.0.0.0", port=int(os.getenv("SERVICE_PORT")))
```

In the above, we enable CORS, that is we kindly ask browsers to allow websites to fetch from this service, even if the website is hosted on a different origin. In a production setting, we might want to restrict the allowed origin to actual websites. While, of course, still every malicious indiviual on the world can send requests to our API, they cannot do so directly by means of an unsuspecting user's browser.

Furthermore, we implement a `/health` endpoint which allows us to wait for this service to get ready before launching Nginx. Otherwise, launching Nginx will fail if it becomes ready before the service.

Once, we build and launch the app container with `docker-compose up --build --detach app` on the remote host, SSHing to the remote host and running 

```sh
curl localhost:5555/some-endpoint/
```
should succeed. As a sanity check, launching a container in the same bridge network and using the container name `app` instead of localhost should also resolve. 

Note that Flask serves the API under HTTP and not under HTTPS. However, the app endpoint on port 5555. In stead, Nginx will reverse-proxy requests to the app container and, at the same time, take the role of an HTTPS termination point. Traffic between Nginx and the application container will be unencrypted. If we wanted to also have encryption inside the backend, we would have to re-encrypt it on Nginx (Nginx must, of course, be able to decrypt requests in order to decipher the path and decide on where to route them), e. g. using a self-managed CA internally. 

# Launch the Nginx server

First, let's define the Nginx config file. 

```conf
server {    
    server_name _;

    listen 443 ssl;

    ssl_certificate /etc/letsencrypt/live/api.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.org/privkey.pem;

    location / {
        proxy_pass http://app:5555;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Host $host;
        proxy_redirect off;
    }
} 

server {
    server_name _;

    listen 80;

    location / {
        return 301 https://$host$request_uri;
    }
}
```
In the first _server_ block, we listen to incoming requests on port 443 and enforce HTTPS using the private key and certificate that were obtained previously with Certbot. Independent from the path, request are routed to _app_ - Docker ensures resolvability by the container name - on port 5555 over HTTP. 

In the second _server_ block, we indicate that any request on port 80 shall be redirected to HTTPS.

After launching nginx with `docker-compose up --build nginx`, we should be able to `curl https://api.example.org/square/15` successfully and retrieve `225` as a response.

Because the app container is already running and serving the API, this should work fine. But in a later CI/CD pipeline, we do not want to bring up each service individually and manually issue the command to boot up nginx but rather start all containers automatically using `docker-compose up --build`.

Therefore, let's delay the startup of nginx in a custom entrypoint to the nginx container until a request to the app's `/health` endpoint succeeds:

```sh
until curl --silent http://app:5555/health; do
    echo "App not yet healthy. Waiting ...";
    sleep 1s;
done

curl -v http://app:5555/health
echo "App healthy. Starting nginx...";

bash docker-entrypoint.sh nginx -g "daemon off;"
```


## Launch the auto-renewal Certbot
The certificates issued by a CA expire, typically after a couple months. Let's Encrypt issues certificates with an expiration limit of three months.

To fully automate requesting new certificates when it's time, let's run a sidecar certbot container. However, can we keep serving the API and keep redirecting requests from port 80 to port 443, if we need port 80 to be able to serve the challenge? Instead of serving the challange with the webserver built into certbot as we did for the first certificate, let's now serve the challenge through Nginx! 

To do so, let's first instruct Nginx to serve a directory shared with certbot for all requests to http://$DOMAIN_NAME/.well-known/acme-challenge/, by modifying the Nginx conf. Add the following rule to the second server block _above_ the root `location /` block.

```conf
# ...
# listen 80;

location /.well-known/acme-challenge/ {
    root /var/www/certbot;
}

# location / {
# ...
```

With this configuration, we do the same as before, except requests to `/.well-known/acme-challenge/` prefix will instead serve the directory under `/var/www/certbot`. Now, we must instruct certbot - instead of serving the challenge on its own (which would fail because port 80 is already use by Nginx) - to place the token file in the shared directory.

Therefore, this time, in the container, we will startup certbot with the `--webroot` switch instead of the `standalone` switch. 
```
certbot certonly \
    --webroot -w /var/www/certbot \
    -d $DOMAIN_NAME \
    -m $EMAIL_ADDRESS \
    --rsa-key-size "2048" \
    --agree-tos \
    -n
```

In order to run this command periodically, let's use the following script as the `certbot-auto` image's entrypoint:
```sh
while true; do
    sleep 24h;

    certbot certonly \
        --webroot -w /var/www/certbot \
        -d $DOMAIN_NAME \
        -m $EMAIL_ADDRESS \
        --rsa-key-size "2048" \
        --agree-tos \
        -n
done
```

Certbot will only actually ask Let's Encrypt to issue new certificates if the expiration date is near, that is closer than 30 days. Otherwise, it won't do anything and go back to sleep again for 24h.

To reload the new certs, let's also reload nginx periodically by means of a custom entrypoint script:
```sh
while true; do
    sleep 12h & wait ${!};
    nginx -s reload;
done & \
bash docker-entrypoint.sh nginx -g "daemon off;"
```

This will run `docker-entrypoint.sh` immediately and, after 12h, `nginx -s reload;` for the first time.

The resulting high-level setup for auto-renewing certificates looks like this:

![](auto-renewal-setup.png)


# Conclusion
Even though the post became much longer than expected, I think the TL;DR shows that it is possible to go from zero to an HTTPS-secured API implementation in minutes, once the setup is clear. Even more so, when combined with something like docker-machine's capability to spin up a web server in the personally preferred cloud in 2 minutes. This makes it easy to quickly implement a backend system, e. g. requestable with JavaScript through the `fetch` Web API like from an HTTPS-secured web site. The next step certainly is to put this into a CI/CD pipeline to allow quick re-deployments.

[^dns-poisoning]: One attack vector of consists of compromising the DNS resolution process, so that packets are instead routed to a malicious server (see Brandt et al. 2018, https://pki.cad.sit.fraunhofer.de/media/doc-CCS2018.pdf). In order to make DNS poising more difficult, Let's Encrypt will send multiple GET requests from different locations. 