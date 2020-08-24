---
title: "Remote Docker Hosts in the Cloud for Machine Learning Workflows"
date: 2020-06-22
draft: false
author: Mo Kari
---

# The problem of developing ML models on a MacBook
In a recent blog post, I have argued why I think it is a good idea to develop ML models inside Docker containers. In short: reproducibility. However, if you don't have access to a CUDA-enabled GPU, developing or even only replicating state-of-the-art deep-learning research can be close to impossible, Docker or not. All ML researchers and engineers working on a MacBook have probably been exposed to this complication.

# Using cloud VMs with GPUs
## Overview
Luckily, in times of compute clouds, getting access to a GPU, or even a machine with multiple GPUs or even 100 nodes with 8 GPUs each, is easy (as long as your budget is sufficient). For example, NVIDIA's Tesla T4 GPU - as of writing this post one of NVIDIA's latest GPU architectures - is available in AWS' _g4dn.xlarge_ instance for an on-demand price of about 0.50 €/h.

If you are indeed implementing your deep-learning models with a _"Docker-first approach"_, the cool thing is that you don't care where your containers get executed (as long as a GPU is available from inside the container and maybe as long as your file system mounts make sense; more on the file system later). And we can exploit this to use the beauty of Docker, allowing us to run any `docker-compose` or `docker` CLI command on a remote docker host without modifying it, but simply by adding a `.env` file resp. setting some environment variables, thus creating a seamless usage experience. 

I will use AWS EC2 as an example, even though GCP and Azure have comparable offerings and it seems that some ML-specific cloud vendors such as [Paperspace also support custom containers](https://docs.paperspace.com/gradient/notebooks/notebook-containers/building-a-custom-container). Azure seems to be a worse deal than AWS considering that you only get a Tesla K80 for the same price (as of writing this with a promoted NC6 instance). However, it has to be noted that AWS's _p2.xlarge_ comprising a single K80 is also a very bad bargain, considering it costs twice as much as the _g4dn.xlarge_ for a GPU half as fast. GCP might be especially interesting due to their TPU offerings, though I haven't tried it out yet for this purpose.

I'm also assuming a Unix-like local OS.

## Creating an EC2 instance
To create an EC2 instance and the related items of the tech stack (such as IAM and networking), we could use the AWS console, the AWS CLI, the AWS CLI with CloudFormation, a Terraform template, ... - or we could use `docker-machine`. `docker-machine` is a tool also by the Docker developers that allows managing remote Docker hosts.

On macOS, docker-machine can be installed with brew 😍: `brew install docker-machine`.

Assuming you have your [AWS credentials](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-envvars.html) in the `~/.aws/` folder or in the standard AWS environment variables, we can create a new EC2 instance in the account's default VPC network using: 

```bash
docker-machine create \
    --driver amazonec2 \
    --amazonec2-instance-type g4dn.xlarge \
    --amazonec2-ami ami-049fb1ea198d189d7 \
    --amazonec2-region eu-central-1 \
    --amazonec2-zone a \
    --amazonec2-ssh-user ubuntu \
    --amazonec2-root-size 150 \
    docker-ml
```

This will create a new EC2 instance of type `g4dn.xlarge` (i. e. 4 vCPUs, 16 GB RAM, 1 Tesla T4), using the EC2 Amazon Machine Image with ID _ami-049fb1ea198d189d7_ (referring to the Ubuntu-18.04-based Deep Learning Image with the popular deep-learning frameworks and esp. with the NVIDIA-Docker runtime pre-installed) in Frankfurt's Availability Zone _a_. To check out other AMIs, you could use the [AMI Explorer in the EC2 Launch Instance Wizard](https://eu-central-1.console.aws.amazon.com/ec2/v2/home#LaunchInstanceWizard). The EBS volume that is attached to the instance will be initialized with 150 GB as indicated. Don't be too eager here by setting the root-size parameter much higher than you need. While you can always [increase the volume size](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/recognize-expanded-volume-linux.html), you cannot decrease it (except by creating a new one and copying the old data over), and 10 cents per GB-month is actually not neglectably cheap. The SSH username is set to the default username on Ubuntu AMIs which is `ubuntu`. On Amazon Linux AMIs, it would be `ec2-user`.

As can be seen in the last line of the CLI snippet, the EC2 instance will be named `docker-ml`. This will not only be a name populated to AWS EC2 but also the name to locally refer to the instance when using the `docker-machine` CLI.

Under the hoods, the above command will not only create the EC2 instance and the EBS volume, but also create
- a new key pair and deploy your public key onto the instance, 
- a security group with allow rules for SSH on default port 22, and for TLS-encrypted Docker on default port 2376.

Refer to the [official docs for docker-machine's AWS driver](https://docs.docker.com/machine/drivers/aws/) to check out further parameters, e. g. in order to 
- avoid creating a new key pair and instead deploying an existing public key using `--amazonec2-ssh-keypath`,
- open additional ports, e. g. when exposing a serving endpoint, using `--amazonec2-open-port`,
- set an instance profile, e. g. to allow usage of S3 without wrangling credentials around, using `--amazonec2-iam-instance-profile`.

Furthermore, it will create and deploy x509 certificates that allow 
- encryption of the connection between the Docker client, i. e. your local CLI, and the remote Docker host, as well as 
- authenticating the Docker client to the Docker host, and 
- authenticating the Docker host to the Docker client. 

If you have ever [created custom certificates](https://coreos.com/os/docs/latest/generate-self-signed-certificates.html), [deployed them locally and to the remote Docker host](https://docs.docker.com/engine/security/https/), and [set up the Docker daemon to support bidirectionally authenticated TCP connections](https://docs.docker.com/config/daemon/), you'll probably be very grateful for what is happening there without any manual effort.

When you `cd` into the `~/.docker/machine/machines` folder on your local machine, you should see a folder with the name of the newly created Docker machine. Inside the folder 

- a config file, 
- the SSH keypair as well as 
- the certificates 

to authenticate and be authenticated can be found. 

## Using the EC2 instance
### Starting and stopping the EC2 instance
After creating the EC2 instance, you can boot it up using

```bash
# in this example, the machine was named docker-ml
docker-machine start docker-ml
```

and stop it using `docker-machine stop docker-ml`.

To SSH into the EC2 instance, one can use `docker-machine ssh docker-ml`. Under the covers, this is equivalent to calling `ssh -i ~/.docker/machine/machines/id_rsa ubuntu@xxx.xxx.xxx.xxx`. You can check the current IP address in the EC2 Instances console. 

It's somehow surprising how the `docker-machine` CLI is more efficient to use than the AWS CLI itself. Even if you wouldn't want to use Docker at all, this seems like a ridiculously easy way to create an EC2 instance and manage it. 

### Elastic IP
However, after each reboot, a new IP address will be assigned. 

Therefore, every time after starting the VM again using `docker-machine start docker-ml`, you will have to run `docker-machine regenerate-certs docker-ml` so that the certificates are issued and deployed again for the specific IP at that point in time.

To avoid this, you could now create an AWS Elastic IP (one could also call it static IP) and assign it to the VM, so to ensure the public IP of the EC2 instance is fix. The Elastic IP costs 1 cent for each hour it is not attached to an active VM. After attaching it, the certificates must be regenerated to be re-issued for the new Elastic IP.

### AWS Credentials
If you are using temporary session credentials obtained from an IAM role assumption as I am doing, you will notice that after the credentials used to create the docker-machine expire, `docker-machine` will throw a 400 error with the info, "RequestExpired: Request has expired". Unfortunately, `docker-machine` has stored the initial credentials in the `~/.docker/machine/machines/docker-ml/config.json` and they take precedence over any AWS credentials set in the environment. However, there is an easy fix: edit the `config.json` and remove the lines, containing the Access Key ID, the Secret Access Key, and Session Token. From now on, commands issued to `docker-machine` will resort to the environment variables. 

### <a name="ssh_config"></a> Back to the roots: from docker-machine to plain vanilla SSH
Apart from the `docker-machine ssh`, there is also the `docker-machine scp` subcommand to allow file transfers between the remote machine and local machine. However, should you prefer using plain-vanilla `ssh` and `scp` or should you also want to use `rsync`, you could append the following snippet to your `~/.ssh/config` file. 

```txt
Host ${MACHINE_NAME}
 HostName ${ENTER_YOUR_ELASTIC_IP_HERE}
 Port 22
 User ubuntu
 IdentityFile ~/.docker/machine/machines/${MACHINE_NAME}/id_rsa
```

Afterwards, SSH-ing into the instance is as easy as `ssh ${MACHINE_NAME}`.

As you can see, up to now we actually haven't been relying on Docker or containers itself, but only on the ease of using `docker-machine` to setup a cloud VM. For those people, blatantly ignoring my pleading to use Docker to implement ML models, you guys could stop here, and for example use Visual Studio Code's [Remote extension](https://code.visualstudio.com/docs/remote/ssh) to conveniently work on the cloud VM using SSH. Having set-up the .ssh/config file, will make the EC2 instance available in the VS Code Remote extension.

But I hope after reading my [post](reproducing-ml-models-using-docker.md) on the advantages of using Docker in an ML workflow, you'll come to the conclusion, that you actually want to proceed to using the EC2 instance as a remote Docker host. Actually, the hardest part is done. The rest is a piece of cake.

# Running Docker containers with the EC2 instance serving as a remote Docker host
## Setting up the CLI
When you run `docker run alpine` the container is executed locally. When you run `docker image ls`, images on the local machine are listed. When you run `docker-compose up`, services are spun up on the local machine. So how can we execute commands on the remote machine? Of course, we could SSH into the machine, but then we'll lose the "seamless experience" I have been promising. How do you want to get modified dev files to the remote host to build and execute them there? Using `scp`? Or `git`? Probably, both alternatives are subpar because we neither want to end up in chaos using `scp` nor clashing our git repo, esp. the origin repo, with meaningless dev commits only to do file sharing.

So how can we run these commands locally, but have them executed on the remote machine with the required files sent from the local host to the remote host? The answer is using a remote Docker daemon, running on the cloud VM, and thus having the Docker CLI and the Docker daemon running on separate machines. By setting the `DOCKER_HOST` env var to the EC2 instances's Docker endpoint (e. g. `tcp://xxx.xxx.xxx.xxx:2376`), we instruct Docker to send the build context over the network to the remote host and to build the image there. Since we want to encrypt the connection and authenticate the server, we need to set the `DOCKER_TLS_VERIFY` env variable (to some arbitrary value such as `.`, `1`, `true`, or `false` if you want to reserve yourself a place in hell). To provide the certificates to verify the server with and to authenticate yourself against the server with, we also need to set the `DOCKER_CERT_PATH=~/.docker/machine/machines/docker-ml`. 

Instead of exporting this environment variables by hand, `docker-machine` has us covered again. Running `docker-machine env docker-ml` will produce a source-able shell snippet to export the relevant env vars. As kindly indicated by `docker-machine` when running the command, we can simply use `eval $(docker-machine env docker-ml)` to export the env vars in one go.

Alternatively, for `docker` CLI commands (such as `docker run` or `docker image ls`), we also could also pass the remote Docker host endpoint, using the `-H` arg, enable TLS using args, etc., instead of using the env var approach, which however is obviously less convenient when using the Docker CLI interactively. For `docker-compose`, there is a second good alternative, which is locating a `.env` file in the current directory. Then however, it makes the most sense, to setup an Elastic IP beforehand, so that you don't have to edit `.env` after rebooting the EC2 instance. 

Having the `DOCKER_HOST`, `DOCKER_TLS_VERIFY`, and the `DOCKER_CERT_PATH` env vars set, we can now simply run `docker` and `docker-compose` commands which are executed on the remote host instead of on the local computer. From a user perspective, there's is no change in the experience: Whether one is building and running on a machine-local Docker daemon using the CLI, or whether one is building and running on a remote Docker daemon using the CLI, doesn't make difference. With two exceptions: latency and file system mounts.

## Latency
Because you have to send the build context over the wire, you'll probably notice a longer delay between entering the _build_ command and seeing the first layer being built or reused. However, if one is using `.dockerignore` properly, makes effective use of caching and is following good practices of separating code and data, it shouldn't be a problem to keep the build context small. To speed up the image build process, it is also useful to consider using Docker [BuildKit](https://docs.docker.com/develop/develop-images/build_enhancements/) instead of Docker's default build system. Instead of always completely transferring the build context, BuildKit will determine cache invalidation per layer on the client machine, thus reducing the number of bytes to be sent over the wire dramatically, esp. if you have large "static" files (e. g. model weights, that you want to embed directly). To enable BuildKit, export `DOCKER_BUILDKIT=1` to the environment. `docker-compose` does not support BuildKit natively, but we can also export `COMPOSE_DOCKER_CLI_BUILD=1` so that `docker-compose` simply acts as a wrapper around the Docker CLI[^buildkit-with-compose], resulting in a command such as

```sh
DOCKER_BUILDKIT=1 COMPOSE_DOCKER_CLI_BUILD=1 docker-compose up --build
```

A positive change in latency is that you'll probably notice a significant speed-up when pulling and pushing images from and to the image registries; at least for me, my home-internet connection is slower than the internet connection of a high-bandwidth EC2 instance.

## File System
Unfortunately, there is one thing that breaks the ephemeral character of containers in this setup, and it is going to cause us a bit of an inveterate headache. 

Somehow, we have to 
- get data into the running container, and
- get data out of the running container, probably after it has finished.

Docker offers the possibility to mount directories from the _Docker host_'s files system into the container - only from the _Docker host_'s file system into the container. And this is were my claim of a seamless experience starts to crumble a bit. In the client-server setup I have been describing throughout this post, there is a Docker client - e. g. your laptop - and a _Docker host_ running the Docker daemon to actually build and run the container. When running a container, we can only mount a directory from the _Docker host's_ file system, not from the Docker client. However, you would probably rather mount a directory from the Docker client's file system - e. g. from your laptop - where you are also running your IDE and your source control, etc. But this is not possible. 

There are different approaches to cope with that. Depending on your dataset size and other factors, maybe you have all your data in an object store such as S3 anyway. If you're building the ML model and its container from scratch, then it might be a good idea to simply not bank on a persistent file system but stream all data from the object store once you need it. Refer to [my post on storage](storage) for a more holistic view on storage for ML and to learn more about streaming data into a container from an object store.

However, sometimes we will not want to meet this ambition of a fully ephemeral container without file system mounts, because we don't want to create an S3 bucket, an IAM policy and role, provision the credentials so that the container can ... - yeah, you get the point. _Not using_ a file system mount can be an extra effort. At other times, it might not be at our discretion of whether to use a local folder, or stream from and to an object store, but will have to live with what is given. E. g., when you are replicating ML research using code published along with their papers, authors will generally assume that training or test data is in some folder in the repo. 

To define a Docker file system mount, we can use `docker-compose` (instead of having to pass the paths through the Docker CLI). For example, a simple `docker-compose.yml` look like this:
```yaml
# docker-compose.yml 
version: "2.4"

services:
  object-tracking:
    # build time
    image: object-tracking
    build:
      context: .

    # run time
    runtime: nvidia # {nvidia | runc}
    shm_size: 4gb
    volumes: 
      - /home/ubuntu/object-tracking/data:/exchange/data
      - /home/ubuntu/object-tracking/output:/exchange/output
      - /home/ubuntu/object-tracking/checkpoint:/exchange/checkpoint
```

The `docker-compose.yml` describes the parameters to run and build the container image _on the remote host_. This _includes_ the file system mounts, i. e. a `docker-compose.yml` will contain the absolute file system path _in terms of the remote Docker host_. We can not use relative paths, and we have to indicate a path that exists on the remote Docker host. There are two things to note here: 

First, since we have cannot indicate relative paths in a volume definition in the `docker-compose.yml` file, it is machine-specific. If you want to run the same container on your local machine, modify the `docker-compose.yml` file with the corresponding volumes section accordingly, or use a `docker-compose.override.yml`. 

Second, if mounting the remote file system into the container executed on the remote host, you probably will have to find a mechanism to also exchange data between your local machine and the remote machine. Two approaches come to mind. One approach is to use an SSHFS mount. And yes, of course, `docker-machine` once again helps us out here and supports this out-of-the-box. E. g.:

```sh
# create a mount point with an arbitrary name, e. g. mnt
mkdir mnt 

# create a folder with a file on the remote host
docker-machine ssh docker-ml "mkdir -p test-dir && cd test-dir && echo 'Hi :)' > test-file.txt" 

 # mount the remote host to the local dir
docker-machine mount docker-ml:test-dir mnt

# show the files of the remote host inside the mounted drive
ll mnt
> .
> ..
> test-file.txt

# copy data, checkpoints, etc. over, run the container using docker-compose with the Docker volume mounts defined there, and finally have a look at your model's output)
# ... 

# unmount the volume
umount mnt
```

To get this straight: we're talking about two different mounts here:
- First, mounting the remote file system into your local file system 
- Second, mounting the remote file system into the container executed on the remote host

If you prefer creating actual copies, `rsync` is a good match. 

Assuming you have setup the [SSH config](#ssh_config), you can simply run 
```sh
rsync -ric \
    object-tracking/data/ \
    docker-ml:object-tracking/data/
```
to sync files from the local folder exchange/data to the remote folder, if and only if they are non-existent or different on the remote. Swap source and target to sync files in the other direction. 


# Conclusion
This post has given some guidance on how to setup an EC2 instance appropriate for deep learning using `docker-machine`, and how my workflow looks like using it. 

To learn more about useful Dockerfile and Compose file templates for GPU-enabled ML containers take a look at [my post on reproducible ML research](/posts/reproducible-ml-using-docker).

[^buildkit-with-compose]: [https://github.com/docker/compose/issues/6440#issuecomment-592939294](https://github.com/docker/compose/issues/6440#issuecomment-592939294)