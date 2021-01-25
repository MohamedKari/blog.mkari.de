---
title: "A minimum viable CI/CD chain for deploying docker-composed applications to a single remote Docker host"
date: 2020-11-29
draft: False
author: Mo Kari
summary: A minimum viable setup for deploying a set of docker-composed containers to a single Docker host in your preferred cloud through a GitHub Actions workflow. This post extends the previous one on secure APIs. 
---

This post shows a minimum viable setup for deploying a set of docker-composed containers to a single Docker host in your preferred cloud through a GitHub Actions workflow. It extends the previous post on [secure APIs](/posts/secure-apis).

# TL;DR
1. Create a gitignored .env file with secrets
2. Adapt your docker-compose file, so that it reads secrets from the environment
3. Push the .env secrets and the Docker daemon socket certificates, key and IP to the GitHub Actions Secret store
4. Add the cicd.yml file to .github/workflows


I'll assume that you're 
- working on MacOS,
- using docker-compose to launch your containerized application,
- used docker-machine to create the remote machine,
- using GitHub for VCS and CI/CD, 
- are only using a single deployment tier (dev = production).

# Overview
Even in times of container management platforms, it sometimes might be desirable to deploy a single container with absolutely no scalabilty, availability or fault-tolerance guarantees, and even with no split-traffic testing whatsoever. The most important thing however, even for a tiny deployment, often is just being automated. Why? Because things such as the name of the server to ssh to, the directory to cd into, and the name of an image to launch, are things not worth remembering. 

Let's assume you're developing a small and non-critical application backend in a GitHub repo comprising a single containerized service, or even multiple services, described by a `docker-compose.yml` spec – for example, an application serving an HTTPS-secured API. Even for such a small and non-critical application, good practices make you fast. One good practice is to automate stuff, e. g. the deployment of the application. Let's extend the [API-driven and HTTPS-secured application presented in a previous post](/posts/secure-apis) by a CI/CD and deployment pipeline.

One of the Docker daemons's properties I really like and rely on often, is its network transparency. Whether you operate on a remote or on the local host makes nearly no difference. All that's required is to set some environment variables that indicate
- the URL to the remote host's Docker daemon socket and
- the path to the certificates for authenticating the client to the server and vice versa.

This network work transparency makes it dead easy to spawn up a container on a remote host without the need to deal with SSH certificates, in particular, if docker-machine was used to create the remote host, because it conveniently deploys the certificates used for authentication as part of the machine creation in your favorite cloud. 

That is, for CI/CD, if you have spun up the deployment target server with docker-machine (meaning you have a server running Docker and exposing its certificate-secured Docker daemon through TCP, and you have matching client certificates), the hardest part is to make these certificates available on the build runner. 

# Storing secrets in the CI/CD system
For the purpose of this blog post, let's assume your source of truth for secrets

1) are certificates created by docker-machine on your local dev computer 

```
~/.docker
└── machine
    ├── certs
    │   ├── ca-key.pem
    │   ├── ca.pem
    │   ├── cert.pem
    │   └── key.pem
    └── machines
        └── web-mkari
            ├── ca.pem
            ├── cert.pem
            ├── config.json
            ├── id_rsa
            ├── id_rsa.pub
            ├── key.pem
            ├── server-key.pem
            └── server.pem
```

2) a gitignored `.env` file in the repo directory.

```.env
# .env
DOMAIN_NAME=...
EMAIL_ADDRESS=...
GITHUB_TOKEN=...
REPO_OWNER=...
REPO_NAME=...
DOCKER_MACHINE_NAME=...
```

On the local machine, in order to set the values from the `.env` to the environment I usually `source env.sh` (or `. env.sh` in a Makefile):

```sh
# env.sh
export $(cat .env |grep "^[^#]")
```

To access these secrets from the GitHub Actions build runner, we could use 
1. tools like https://git-secret.io/ or https://www.agwa.name/projects/git-crypt/ that allow encrypting secrets directly in git by offering commands to encrypt and decrypt it, or
2. we can use GitHub Actions Secrets which is a key-value store, provided by GitHub and associated with the GitHub repo.

If we rely on alternative 1), then we would need to decrypt the encrypted files in version control on the build runner using the corresponding tool. However, in order to decrypt the encrypted files, we would need to use a key. And the original questions pops up: How do we get the key to the build runner? Now, there's only the option of GitHub Actions Secrets left. So, there's no way out. We need to get at least one secret to the build runner, and because GitHub manages the build runners on our behalf, we must use the built-in GitHub Actions Secrets in any case. Therefore, let's use only GitHub Actions Secrets and discard the idea of involving alternative 1).

So how do we get our secrets to GitHub actions? We can either copy-paste them using the GitHub UI, or we can use GitHub API. Since, copy-pasting all relevant certificates is a bit tedious, let's opt for the API-based approach. Due to the encryption part, it's not easily doable using `curl`, so I've been using a tiny Python CLI: https://gist.github.com/MohamedKari/d6a2a7a6cdfe5aee32a6c8eefd6029be.

To run it, fetch and run the `gh-secrets.sh` file which will create a new python virtual env, activate it, install the project's Python dependencies, and then fetch the python file it self. 
```sh
bash <(curl -S https://gist.githubusercontent.com/MohamedKari/d6a2a7a6cdfe5aee32a6c8eefd6029be/raw/gh-secrets.sh)
source .gh-secrets/bin/activate
```

So, let's get the certificates and key over 
```sh 
# set all environments variables from .env file 
source env.sh

# store the remote host IP, the CA certificate (used for authenticating the server), and the client certificate and key (used for authenticating the client) in the GitHub Actions Secrets store
# If you're not using docker-machine, you can set these values manually with keys DOCKER_HOST, CA, CERT, and KEY using `python github-secrets.py set ...`
python gh-secrets.py deploy_docker_machine_certs $REPO_OWNER $REPO_NAME $DOCKER_MACHINE_NAME
```

Because the build runner will start the Docker containers on the remote Docker host through `docker-compose` with certain application-specific arguments (e. g. in this case, for certbot to request Let's Encrypt certificates with the correct domain), we also need to store sensitive application-specific arguments in GitHub. 
```sh
python github-secrets.py set $REPO_OWNER $REPO_NAME $EMAIL_ADDRESS $EMAIL_ADDRESS
python github-secrets.py set $REPO_OWNER $REPO_NAME $DOMAIN_NAME $DOMAIN_NAME
```

`python github-secrets.py list` should show the names of all Secrets in the repo.

# Specifying the integration and deployment pipeline

```yml
name: CI

on: 
  - push
  - pull_request

jobs:
  build-deploy:
    name: Build and deploy

    runs-on: ubuntu-latest

    steps: 
      - uses: actions/checkout@v2

      - name: Check secret existence
        env: 
          CA: ${{ secrets.CA }}
          CERT: ${{ secrets.CERT }}
          KEY: ${{ secrets.KEY }}
          DOCKER_HOST: ${{ secrets.DOCKER_HOST }}
          DOMAIN_NAME: ${{ secrets.DOMAIN_NAME }}
          EMAIL_ADDRESS: ${{ secrets.EMAIL_ADDRESS }}
        run: |
          if [ -z "$CA" ]; then exit 100; fi
          if [ -z "$CERT" ]; then exit 100; fi
          if [ -z "$KEY" ]; then exit 100; fi
          if [ -z "$DOCKER_HOST" ]; then exit 100; fi
          if [ -z "$DOMAIN_NAME" ]; then exit 100; fi
          if [ -z "$EMAIL_ADDRESS" ]; then exit 100; fi
 

      - name: Build images
        run: docker-compose build

      #- name: Intra-Container test
      #  run: |
      #    docker-compose -f docker-compose.test.yml up

      - name: Deploy container to remote machine
        env:
          CA: ${{ secrets.CA }}
          CERT: ${{ secrets.CERT }}
          KEY: ${{ secrets.KEY }}
          DOCKER_TLS_VERIFY: 1
          DOCKER_HOST: ${{ secrets.DOCKER_HOST }}
          DOCKER_CERT_PATH: /home/runner/work/${{ github.event.repository.name }}/${{ github.event.repository.name }}/certs
          DOMAIN_NAME: ${{ secrets.DOMAIN_NAME }}
          EMAIL_ADDRESS: ${{ secrets.EMAIL_ADDRESS }}
        run: |
          mkdir certs
          printf '%s' "$CA" > certs/ca.pem
          printf '%s' "$CERT" > certs/cert.pem
          printf '%s' "$KEY" > certs/key.pem  
          docker-compose down
          docker-compose up --detach
          docker ps
      - name: Run smoke test
        timeout-minutes: 1
        env: 
          DOMAIN_NAME: ${{ secrets.DOMAIN_NAME }}
        run: |
          until curl -s https://$DOMAIN_NAME/health; do
            sleep 5s
          done
          curl -v https://$DOMAIN_NAME/health
          echo "Healthy.";
```

The build runner will 
- checkout the repo, 
- check if all required secrets (as indicated manually) are set to GitHub Actions secrets store and are reabable from the environment, 
- write the certificates to a directory on disk, 
- set a path to DOCKER_CERT_PATH environment pointing to the certificate directory, 
- build the Docker images, 
- shutdown running containers on the remote host, 
- start the containers from the newly build images, and
- do a smoke test against a `/health` endpoint exposed by one of the launched containers.

# Conclusion
Gotta love CI/CD. 
![](github-actions-ui.png)