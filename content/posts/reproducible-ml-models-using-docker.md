---
title: "Reproducible ML Models using Docker"
date: 2020-07-05
draft: False
author: Mo Kari
---

_Reproducing ML models can be a pain. And this is not even talking about managing model reproducibility with different datasets, features, hyperparameters, architectures, setups, non-deterministic optimization or about model reproducibility in a production-ready setup with constantly evolving input data. No, what I am talking about is getting a model which was developed and published by a different researcher to run on your own machine. Sometimes, or more like most times, this can be a nerve-wrecking endeavor. This is especially true if the model makes use of GPU acceleration and thus requires GPU-specific drivers and compilations. However, the use of Docker as described in this post promises a way out._

# Causes of non-reproducibility
As a basis for my own research, I have lately been reproducing a lot of models in the domain of deep-learning-based computer vision. However, it turns out that getting other researcher's code to run on your own machine is a mostly unpleasant endeavor as a result of many factors.

## Code or instructions are bad
Of course, some researchers beautiful code with a clean CLI that states in a couple of lines how to fetch the dataset, maybe fetch the pre-trained weights, start training, produce the same evaluation tables and sample figures used in the published paper and run predictions for custom input data. However, that is quite rare. Many times, you will need to download some dataset split from the original dataset publisher, download the weights from the researcher's Google Drive, rename the files, try out different placements in the repo directory hierarchy in an effort to eradicate a probably related "Tensor must match size (8) at non-singleton dimension". In times of CI/CD, where we have the ambition to make building, testing, and even deploying a large-scale distributed system as easy as committing to the VCS, we shouldn't aim for less than running the full model pipeline by typing `make`.

## Dependency management is bad
Independent of the code quality and the instructions to run the code, many times dependency management is a precarious topic. Probably, in 3 out of 5 cases, the research results that I am replicating from 2019 will throw an ImportException `cannot import name 'imread'` when running them because of a breaking change from [SciPy version 1.2. to 1.3](https://docs.scipy.org/doc/scipy/reference/release.1.3.0.html#scipy-interpolate-changes). Here, the remedy is easy: using a `requirements.txt` with pinned versions and also including transitive dependencies instead of only indicating directly imported packages. 

Also, usage of `git submodule`s is not as prevalent as one might expect given they allow explicitly depending on a specific version hash. Instead one often instructed to `git clone` a repo that might have changed significantly in the time between model release and model reproduction leading to further reproduction issues. I'd consider it a good practice to fork the repos your code depends on and then `git submodule add` them to the model repo a better practice. Thus, one is safeguarded against change or removal of the dependencies.

But unfortunately, there also software dependencies that are not fixable this easy. Besides depending on `pip` or `conda`-installable Python packages or clone-able repos, model code may depend on a specific Python version itself or specific versions on CUDA and cuDNN. While we can use virtual Python environments for different Python versions, juggling multiple CUDA installations depending on different GCC versions with the different components of the CUDA tool stack and keeping track of the corresponding environment variables or symlinks can be quite inefficient to put it nicely.

## The world is bad
However, the problem is worse than this: Sometimes, when models include custom layers with custom CUDA kernels, a certain version of the Nvidia CUDA Compiler `nvcc` with corresponding CUDA dependencies is required. Not providing full backward compatibility, newer CUDA versions can lead to irksome errors at [compile time or runtime](https://github.com/open-mmlab/mmdetection/issues/385) à la `undefined symbol: __cudaRegisterFatBinaryEnd`. So, upgrading the CUDA version is not always an option. However, sticking to the old version of `nvcc` will not allow you to compile for the latest GPU architectures[^1]. In essence, the software is not compatible with the hardware. 

What's the solution here? To be honest, the Docker-based approach described in the following does not solve the problem of software-hardware incompatibility. But if you are following it, it will allow you to deploy your container to a different machine with a different GPU or different set of GPUs with very little effort - [as described here](/posts/remote-docker-for-ml/). And in times of cloud, it is much simpler to adapt hardware than to adapt software. 

# Docker for Machine Learning as a remedy

Docker is a standard in application development. However, it has certain properties that make it also useful for machine learning in a non-production setting. These are:

1. Reproducibility
2. Reproducibility
3. Reproducibility

As a consequence of this reproducibility, the code can easily be deployed and executed on machines with a better GPU, with more GPUs – or belonging to a different researcher. 

It also makes switching between different projects easy as well as trying out multiple CUDA versions for a single project (if it is not stated which version you need for the repo you're trying to get to run). 

Furthermore, it improves software design as one is forced to think about

- separation of code and data, 
- separation of building and running the model, and
- explicitly stating the interface, 

at least if done correctly and not negligent.

# Setup
As a MacBook user, I don't have a decent built-in GPU. Instead, I use a VM in the cloud, that has a GPU and [nvidia-docker](https://github.com/NVIDIA/nvidia-docker) installed. Currently, I mostly use AWS EC2 `g4dn.*large` instances [serving as a Docker host](posts/remote-docker-for-ml/) as it offers a modern Tesla T4, sometimes upgrade to a `p3.*large` for the Tesla V100, or downgrade to a `p2.*large` for a Tesla K80 if required for compatibility. 

AWS' Deep Learning AMI - the VM image - has the Nvidia drivers and nvidia-docker pre-installed. I suppose the same is true for [Google's Deep Learning VM](https://cloud.google.com/ai-platform/deep-learning-vm/docs/introduction) and [Microsoft's Data Science VM](https://docs.microsoft.com/en-us/azure/machine-learning/data-science-virtual-machine/tools-included), even though I haven't tried it. Since version 19.03, Docker natively supports GPU acceleration by passing  `--gpus all` to the Docker CLI. However, there is [currently no docker-compose equivalent](https://github.com/docker/compose/issues/6691), which is why I still rely on the separate `nvidia-docker2` packages. 

With `nvidia-docker2` installed (as said, pre-installed in the AWS Deep Learning AMI), it is possible to pass the `nvidia` container runtime to the Docker CLI with `docker run --runtime nvidia ...` (or using the corresponding `docker-compose` option), which provides access to the host's GPUs and the driver-dependent software, in lieu of using Docker's default container runtime `runc`. 

However, the `runtime` argument can only be passed to `docker run`, not to `docker build` (and the option is equivalently ignored during `docker-compose build`). To make the GPU available during the image build process (as it is for example required when [building Detectron2 with GPU support](https://detectron2.readthedocs.io/tutorials/install.html#common-installation-issues)), we need to globally set the Docker container runtime to `nvidia` [as default](https://github.com/NVIDIA/nvidia-docker/wiki/Advanced-topics#default-runtime) by adding the `default-runtime` field in the `/etc/docker/daemon.json` file:

```json
{
    "runtimes": {
        "nvidia": {
            "path": "nvidia-container-runtime",
            "runtimeArgs": []
        }
    },
    "default-runtime": "nvidia"
}
```

After restarting the Docker daemon using `sudo systemctl restart docker`, the GPUs are available from inside the container during the build process.

However, note that overriding the default runtime during the image build process as described only works when using the default Docker build engine. I didn't look into it yet but when using BuildKit, you probably need to override the OCI Worker Binary somehow.

# Code samples
In the following, I gathered up some Dockerfiles I have used in the past to replicate research results. I have not redacted them for this post and therefore they also reflect my learning experience (fancy for: there might be some bad practices in there such as installing from time-variant sources such as not-hashed git repos) as well as the fact that they partially were fixes to quickly get other people's code to run to evaluate its applicability for my own research. 

Depending on whether `conda` and an `env.yml` or `pip` and a `requirements.txt` is used, different snippets might be useful. When I write code myself, I automatically generate the `env.yml` or the `requirements.txt` (e. g. using `conda env export > env.yml` or `pipenv lock -r > requirements.txt` resp.) and commit the pinned-version file to version control as well.

Depending on whether the Deep Learning framework is expected to be already or installed or whether it is installed in the build process and whether the required combination of framework and CUDA version exists, one can choose to either build from a framework base image or to fall back to the desired CUDA base image and install the framework on top.

## Common Dockerfiles

### PyTorch and Python OpenCV

```Dockerfile
##### CUDA & TORCH #####
FROM pytorch/pytorch:1.4-cuda10.1-cudnn7-devel

WORKDIR /app

##### OPENCV2 DEPENDENCIES #####
RUN apt-get -y update && apt-get -y install \
        libglib2.0-0 \
        libsm6 \
        libxrender-dev \
        libxext6

##### PYTHON PACKAGE DEPENDENCIES #####
RUN pip install --upgrade pip

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

##### Repo-specific compilation of custom CUDA kernels #####
COPY lib/resample2d_package lib/resample2d_package
COPY models/correlation_package models/correlation_package
COPY install.sh install.sh
RUN bash install.sh

ENV PYTHONUNBUFFERED=.

COPY . .

ENTRYPOINT [ "bash", "run.sh" ]
```

### CUDA & pyenv
```Dockerfile
##### CUDA #####
FROM nvidia/cuda:9.0-cudnn7-devel-ubuntu16.04

SHELL ["/bin/bash", "-c"] 

##### PYENV & PYTHON #####
# Install pyenv dependencies & fetch pyenv
# see: https://github.com/pyenv/pyenv/wiki/common-build-problems
RUN apt-get update && \
    apt-get install -y build-essential libssl-dev zlib1g-dev libbz2-dev \
    libreadline-dev libsqlite3-dev wget curl llvm libncurses5-dev libncursesw5-dev \
    xz-utils tk-dev libffi-dev liblzma-dev python-openssl git && \
    git clone --single-branch --depth 1  https://github.com/pyenv/pyenv.git /.pyenv

ENV PYENV_ROOT="/.pyenv"
ENV PATH="$PYENV_ROOT/bin:$PATH"
ENV PATH="$PYENV_ROOT/shims:$PATH"

ARG PYTHON_VERSION=3.6.4

RUN pyenv install ${PYTHON_VERSION} && \
    pyenv global ${PYTHON_VERSION}


##### PYTHON PACKAGE DEPENDENCIES #####
WORKDIR /app
COPY 3d-tracking/requirements.txt /app/3d-tracking/requirements.txt
RUN pip install -r 3d-tracking/requirements.txt

##### APPLICATION #####
COPY . .

# bad for caching, since they get rebuild every time a bit changes in the build context, 
# but hard to isolate from the rest of the repo
RUN cd /app/3d-tracking && bash scripts/init.sh
RUN cd /app/faster-rcnn.pytorch/ && bash init.sh

ENTRYPOINT [ "python", "run.py" ]
```

### CUDA, Conda and Detectron2
```Dockerfile
##### CUDA #####
FROM nvidia/cuda:10.2-devel-ubuntu18.04

##### CONDA #####
RUN apt-get update -y && \
    apt-get install -y \
        wget
    
RUN wget --progress=dot:mega https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh && \
    bash Miniconda3-latest-Linux-x86_64.sh -b

ENV PATH="/root/miniconda3/bin:${PATH}"
ENV PATH="/root/miniconda3/condabin:${PATH}"

##### PYTHON PACKAGE DEPENDENCIES #####
WORKDIR /app

# env.yml contains desired torch version
COPY env.yml env.yml
RUN conda env update -f env.yml --name base

# required by opencv-python, https://github.com/conda-forge/pygridgen-feedstock/issues/10#issuecomment-365914605 
RUN apt-get install -y libgl1-mesa-glx

##### DETECTRON2 #####
# pycocotools always asks for special treatment
RUN apt-get install -y git gcc && \
    pip install cython && \
    pip install -U 'git+https://github.com/cocodataset/cocoapi.git#subdirectory=PythonAPI'

# Using a prebuilt Detectron2 release to make life easier
RUN python -m pip install detectron2 -f \
        https://dl.fbaipublicfiles.com/detectron2/wheels/cu102/torch1.5/index.html

##### APPLICATION #####
ENV PYTHONUNBUFFERED=.

COPY sds sds

ENTRYPOINT [ "python", "-m", "sds"]
```

## docker-compose
To make sure others can start the container as intended, we either have to provide a shell script or Makefile that calls the Docker CLI with the desired parameters, or else have to provide a `docker-compose.yml` file. I do both by setting all parameters in the `docker-compose.yml` file and provide the minimal `docker-compose run`, `build`, or `up` commands in a Makefile.

A typical `docker-compose` file I frequently use looks like this:

```yml
# docker-compose.yml
version: "2.4"

services:
  tracking:    
    # build time
    build:
      context: .
    
    # run time
    runtime: nvidia # {nvidia | runc}
    shm_size: 4gb
    volumes: 
      - /home/ubuntu/share/tracking/input:/app/tracking/input
      - /home/ubuntu/share/tracking/output:/app/tracking/output
      - /home/ubuntu/share/tracking/checkpoint:/app/tracking/checkpoint   
```

The runtime argument is only supported in compose file version 2. However, if you overrode the default runtime to be `nvidia` (also to make GPUs available during the build), you can then use version 3. I personally still stick to version 2.4 if I don't need version 3 specifically because it allows switching between CPU and GPU support. 

## The Entrypoint
While it might be valid to have a shell as an entry point during model development, I suggest to allow for a minimum-interaction interface by providing a meaningful entry point to the application. In an upcoming post, I will suggest using an interface that provides the set of functions most supervised-learning models will offer, such as preprocess, train-and-evaluate, infer, serve, ... This means that there might an entry point such as `ENTRYPOINT [ "python", "run.py" ]` , where we can override the default action by using `docker-compose run some_model train-and-evaluate` and still access a container interactively using `docker-compose run -it --entrypoint bash some_model`.

# Conclusion
I outlined how Docker can help the reproducibility of machine learning with GPU acceleration. Aside from making research results more accessible, this also has the potential to increase the efficiency of ML engineering in enterprise contexts as it diminishes the gap between the development and productionization of models. 

However, the great thing is that it advantageous to use even in a "private" workflow for models that are not planned to be productionized or published. Being able to easily run a model without thinking about installing and exposing the correct CUDA version on a system is an ease. The first thing I do once I what to run model code from a GitHub repo is creating a Dockerfile for it. 

Furthermore, Docker makes it easy as pie to seamlessly work on both a local machine and on a remote VM in the cloud that can be easily adapted to the hardware needs. See my post [on remote docker hosts for ML](/posts/remote-docker-for-ml/) for more info.


[^1]: For the CUDA compilation process, one has to pass the target GPU architecture to `nvcc`, for example by setting the `arch` argument (e. g. `-arch=sm_75`) or the `gencode` argument (e. g. `-gencode arch=compute_75,code=sm_75`)  to the correct version where `75` indicates the _compute capabillity_ version _7.5_ of the specific GPU, in this case the Tesla T4 attached to the _g4dn.*_ instances. The K80 has CC version 3.7 and the V100 has CC version 7.0. The by far best reference to look up the CC version is the [CUDA site on Wikipedia](https://en.wikipedia.org/wiki/CUDA#GPUs_supported). Alternatively, they can also be found on the [Nvidia developer sites](https://developer.nvidia.com/cuda-gpus), or programmatically read-out using PyTorch's [`torch.cuda.get_device_capability(device)`](https://pytorch.org/docs/stable/cuda.html#torch.cuda.get_device_capability).