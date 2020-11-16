---
title: "Running an X Server with Indirect GLX Rendering on MacOS for containerized applications with GUIs"
date: 2020-11-16
draft: false
author: Mo Kari
---

# Intro
For my latest research, I am looking into visual SLAM (e. g. [ORB-SLAM2](https://github.com/raulmur/ORB_SLAM2)). Since VSLAM libraries are designated for running efficiently on embedded systems, it is generally programmed in C/C++ and designed with just Linux in mind (even though, for example, [in version 2, ROS also aims for compatibility with MacOS](https://index.ros.org/doc/ros2/Installation/Crystal/macOS-Install-Binary/)). 

As a MacBook user, this becomes "interesting". Of course, Docker makes it easy to run libraries for Linux. However, once the software also comprises graphical UIs, e. g. for visualization, things get a bit more complicated. 

Of course, anything that involves GPUs on macOS is a nightmare. Not only does the GPU cause overheating if you do crazy things such as connecting a second display, and, hence, heat-throttling, but also developing against it is also _very not fun_. The solution for CUDA-based ML is to simply not use the Mac and do it to remote Linuxes (see my post on [remote docker hosts for ML](/posts/remote-docker-for-ml/). Analogously, it might be interesting to compute the visualizations in real-time on a remote GPU (e. g. using a GPU-accelerated VM at AWS) and simply [tether the rendering results to the developer machine using VNC](https://carla.readthedocs.io/en/0.9.7/carla_headless/). 

An alternative to VNC is to render the hardware-accelerated GUI on the _developer machine's GPU_ using the X Window System. This is what I'll show in this post. The X Window System follows a client-server approach where the X Server is connected to the user I/O devices (screen, keyboard, mouse) and an X client can communicate to the X Server through the [X protocol](https://www.x.org/releases/X11R7.6/doc/man/man3/), either on the same host or over the network. In the context of this post, the main idea is to run the actual algorithms with all their dependencies in a container and only run the visualization outside of it. Communication between the code running inside the container and the GUI is done using X in the omnipresent version from 2012, X11.

Apart from latency issues, the main problem of the alternative described in this post, is that the GPU driver software must be correctly installed on macOS and it must compatible with the code running inside the container. This, of course, defeats the idea of containerizing the code in the first place and defining all dependencies through software. E. g. [ORB-SLAM2](https://github.com/raulmur/ORB_SLAM2) and ROS2 RViz2 depend on the OpenGL API for 3D rendering which is is run in _Mac land_ and not in _container land_. However, Apple does not supporting OpenGL anymore and has instead promoted its own Metal 3D graphics library. However surprisingly, at least for research purposes, libraries often do not require the late versions of OpenGL - e. g. ORB-SLAM2's visualization module is happy with OpenGL 1.4 from 2002, so that its still worth a try. 

# Setup up the Mac
Assumming a macOS Catalina (10.15.4) and brew, install XQuartz using `brew install xquartz`. This will install a macOS-compatible X Server and a variety of tools and libraries (such as `xeye`, OpenGL 1.4, and the `glxgears` test app). After installing XQuartz and opening up the macOS-native Terminal and running `xeyes` and `glxgears` should automatically launch the X server and spin up windows on the local machine. If it doesn't, open up XQuartz manually using the Spotlight search. 

While `xeyes` renders without OpenGL-provided GPU acceleration, `glxgears` will use GPU acceleration through direct rendering - that is use X server for window management only, but bypass it for computing graphics operations directly on the GPU. Since code in the Docker container won't have access to the GPU directly, we need to use OpenGL's feature for indirect rendering so that the X server takes the role of a proxy to the GPU:
 
```sh
defaults write org.macosforge.xquartz.X11 enable_iglx -bool true
```

In the above, `xeyes` and `glxgears` take the role of _X clients_. [ORB-SLAM2](https://github.com/raulmur/ORB_SLAM2) is the X client I actually want to run in a container.

# Running a container as an X client in a remote machine and the XQuartz X Server on the MacBook
The setup I'll describe in this section can be structured as follows:
![](setup.png)

## Setting up SSH
In order to make sure, an X client can connect to the X server over the internet, we use SSH's capability for X11 forwarding. The SSH daemon will inject a `DISPLAY` environment variable that indicates a virtual X server display address and 
- forward all X requests to the virtual display that are taking place on the remote host  
- to the X server running on the developer machine through the SSH tunnel. 

Make sure the SSH daemon on the remote host allows X11Forwarding:
```sh
ubuntu@mo:~$ cat /etc/ssh/sshd_config | grep -i X11Forwarding
X11Forwarding yes
```
If you needed to adapt this, remember to run `sudo service ssh reload`.

If you use [docker-machine](/posts/remote-docker-for-ml.md) to spin up your remote servers, just using `docker-machine ssh` doesn't work because we cannot pass the `-X` argument to enable X11Forwarding for this session. Instead use:
```sh
cd ~/.docker/machine/machines/mo
ssh -X -i id_rsa ubuntu@123.123.123.123
```

Otherwise, just use the SSH command you normally use to connect to your remote server, 
but make sure to use the `-X` argument.

On my MacBook, running `ssh -X` will automatically launch XQuartz. If it doesn't launch automatically, simply launch it manually.

## Running an X and a GLX client on the bare VM
If you don't mind interfering with your OS installation, e. g. Ubuntu, (because you're using a throw-away VM anyway) install the X and GLX test app:

```sh
apt update && apt install -y x11-apps mesa-utils
```

Executing `xeyes` and `glxgears` in the SSH terminal should already work and display windows on your MacBook. 

## Running an X and a GLX client on a remote Docker host
Let's now containerize the `xeyes` and `glxgears` clients. It turns out, for both of them, we don't need a custom Docker image but can just use a plain Ubuntu image and install two packages using apt. 

SSH into the remote host and create the following `docker-compose.yml` file (e. g. using vim). 
```yml
# docker-compose.yml
version: "3.7"

services:
  glx:
    image: ubuntu:16.04
    environment: 
      - DISPLAY
    volumes:
      - /tmp/.X11-unix:/tmp/.X11-unix
      - /home/ubuntu/.Xauthority:/root/.Xauthority:rw
    network_mode: "host"
```

Then, run the `glx-test` service:

```sh
docker-compose run --entrypoint bash glx-test
```

In the container, run 
```
apt update && apt install -y x11-apps mesa-utils 
xeyes
```

Now, `xeyes` should display on your MacBook. Close it and run `glxgears`. It also should now show up on your MacBook. 

You can find the Dockerfile I created for ORB-SLAM2 in [my ORB-SLAM2 fork](https://github.com/MohamedKari/ORB_SLAM2/blob/master/Dockerfile). 

![](orb-slam2-on-mac.gif)

# Running both the container as an X client and the XQuartz X Server on the MacBook
After finishing the above solution and taking a step back, it dawned on me that it doesn't make much sense. While I was able to achieve the desired result of running the V-SLAM code and visualizing it on the MacBook display, the heavy computation on the GPU is also running on the Mac hardware, thus creating dependencies on the macOS installation. 

Originally, I assumed that I would be able to put all dependencies including OpenGL and Graphics drivers into the container. However, what I ended up with, is a container that only runs the CPU-based code on the remote machine, and even at the cost of rendering over the network. So, even though it doesn't solve the dependency problem, it would be at least better to simply run the container locally on my developer machine. So let's have a look how this works.

After starting XQuartz the DISPLAY environment variable (at least when starting the Terminal through the XQuartz menu) contains the display address:
```sh
echo $DISPLAY
/private/tmp/com.apple.launchd.ffq9tVZfPf/org.macosforge.xquartz:0
```

While we could rely on SSH X11Forwarding in the previous setup in order to route X request from the X client on the remote machine to the XQuartz server, now we must employ a different technique - namely `socat`[^socat-use] - to route requests from inside the container to the XQuartz server. `socat` (for socket cat) allows establishing a mapping between two sockets.

```sh
brew install socat
socat TCP-LISTEN:6000,reuseaddr,fork UNIX-CLIENT:\"$DISPLAY\"
```

Then, we can run a container locally on the MacBook using
```sh
docker run -it -e DISPLAY=host.docker.internal:0 ubuntu:16.04
```

Inside the container, `xeyes` and `glxgears` will be able to spin up windows and run OpenGL computations through the `socat` channel.

[^socat-use]: https://gist.github.com/stonehippo/2c2b0972b7d199c78fb94fa9b1be1f5d

# Conclusion
In retrospect of the last three days, even though I haven't tried the maybe superior VNC alternative, I guess the single best alternative is switching to a local Linux machine. 