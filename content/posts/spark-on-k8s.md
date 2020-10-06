---
title: "Native Spark on Kubernetes"
date: 2020-10-06
draft: True
author: Mo Kari
---

_In this post, the different deployment alternatives of Spark on Kubernetes are evaluated. From this, I'll outline the workflow for building and running Spark Applications as well as Spark Cluster-backed Juypter Notebooks, both running PySpark in custom containers. Workloads use AWS S3 as the data source and sink and are oberservable using the Spark history server._

# Table of Contents

- [Development Environment](#development-environment)
- [Spark Terminology](#spark-terminology)
- [Spark on K8s Deployment Alternatives](#spark-on-k8s-deployment-alternatives)
  * [Native Spark on K8s](#native-spark-on-k8s)
  * [Spark Operator for Spark on K8s](#spark-operator-for-spark-on-k8s)
  * [Spark Standalone on Kubernetes](#spark-standalone-on-kubernetes)
- [The Spark Container Image](#the-spark-container-image)
  * [Overview](#overview)
  * [Custom Spark Base Image Build](#custom-spark-base-image-build)
  * [Custom Spark Application Image](#custom-spark-application-image)
- [Running Custom Spark Applications and Notebooks on K8s](#running-custom-spark-applications-and-notebooks-on-k8s)
  * [Prerequisites](#prerequisites)
    + [Role](#role)
    + [Log files](#log-files)
    + [Secrets](#secrets)
  * [Submitting Applications in Cluster Mode](#submitting-applications-in-cluster-mode)
  * [Running Notebooks in Client Mode](#running-notebooks-in-client-mode)
    + [Overview](#overview-1)
    + [REPL Shell](#repl-shell)
    + [Jupyter Notebook](#jupyter-notebook)
- [Spark Driver UI and the History Server](#spark-driver-ui-and-the-history-server)
- [Outlook](#outlook)

# Development Environment

I'm running the following environment:
- OS X 10.15.4
- local Docker 19.03.13 (e. g. `brew cask install docker`)
- Minikube v1.13.1 (`brew install minikube`)
- Apache Spark 3.0.1 with PySpark (`brew install apache-spark`)
- Helm v3.3.4 (`brew install helm`)
- Minikube is serving Kubernetes v1.19.2 (`minikube --memory 8192 --cpus 4 start && kubectl cluster-info`)
- conda 4.8.3 (`brew cask install anaconda`)
- awscli 2.0.34 (`brew install awscli`)

Further, I have created image repos on Docker hub at mokari94/spark-base, mokari94/spark-app, mokari94/spark-history-server and am logged in to the registry.

# Spark Terminology

A central notion of a Spark application is the _driver process_. 
The driver process could run on the developer's machine when using a spark-shell or a locally started notebook, it could run on a gateway host at the edge of a cluster, or a notebook server running on the cluster itself. 
We'll come back to where the driver process runs in a bit.

The _driver process_ distributes a workload across a set of _executors_. 
These executors are processes, running on nodes in the cluster. 
How does the driver process allocate executors on the worker nodes of the cluster?
The answer is the _cluster manager_. 
Upon startup, the driver process will instruct the cluster manager to create a certain number of executors on the cluster. 
The cluster manager will then start each executor and tell them the IP and port of the driver process.
Of course, the cluster manager needs to know the hosts of the cluster and must be able to start processes on them, generally by using an agent running on the node.
Once all executors have reported back to the driver, the driver can distribute _tasks_ among them, e. g. tasks for data transformation. 
Instead of sending the data through the driver over the network to the executors, the driver tells the executors where to find the data on a shared file system. 
This could be an object store such as S3, a distributed file system such as HDFS, or a mounted file system.
Spark relies on data parallelism, that is each executor handles a partition of the overall input data. 
The driver process is in charge of splitting the overall input data into more or less equally-sized partitions that then get assigned to the executors. 
Instead of dumping the transformation result immediately back to the shared file system, the executors keep the result of a transformation in-memory until the driver either instructs the executors to dump it, or to aggregate the data. 
Aggregation could mean that each executor reduces the partition it "owns" to a local result and returns this local result to the driver which then reduces all received results to a global result. Or it could mean that executors need to exchange data between each other before, in the so-called shuffle procedure.

In the so-called _client mode_, the driver process runs in the initiating process, e. g. the developer machine or a gateway machine. 
In the so-called _cluster mode_, the driver program gets deployed to the cluster by the cluster manager first, and then is started as process co-located to the executors, thus improving latency and being independent of the initiating machine. 

In _Spark Standalone_, a cluster is managed by the so-called Spark Master process. By default, it is listening on port 7077.
Each worker node of the cluster needs to run the Spark Worker Daemon process which - upon setup - is registered with the Spark Master running on the master node on port 7077. 
Spark applications are then submitted to the cluster using the `spark-submit.sh` script with the `--master spark://$SPARK_MASTER_HOST:7077` argument. One can also 

# Spark on K8s Deployment Alternatives

## Native Spark on K8s
Since 2018, Spark has [native support for Kubernetes](https://issues.apache.org/jira/browse/SPARK-18278). 
For _Spark on K8s_, we assume that there is a Kubernetes cluster, serving the Kubernetes API at a given url. 
Spark applications are again submitted to the cluster using the `spark-submit.sh` script, however this time indicating the `--master k8s://$K8S_API_URL` argument. Furthermore, one indicates `--conf spark.kubernetes.container.image` pointing to a pullable container image.
Now, instead of asking a running Spark Master to launch executor processes on pre-registered machines, 
the local submission client, running in the local process invoked by `spark-submit.sh`, will create a Kubernetes spec with as many pods as desired executors. The spec is sent to the  Kubernetes API and handled by the Kubernetes schedule. The scheduler schedules the pods, each of them featuring a single container which runs the Spark executor. 
In the current version of Spark, Spark Standalone as well as Spark on K8s can run handle cluster mode and client mode (except PySpark jobs running in cluster mode on Spark Standalone clusters, this doesn't work).
This setup allows to run _custom_ Spark containers on Kubernetes without any prior setup, apart from some role stuff.

## Spark Operator for Spark on K8s
However, running `spark-submit.sh` in an imperative manner and passing a whole lot of config parameters is a bit inconsistent with the declarative `kubectl apply` paradigm. 
Therefore, Google has developed the a Kubernetes Operator for Spark. 
As stated in the [Kubernetes User Guide](https://kubernetes.io/docs/concepts/extend-kubernetes/operator/), Kubernetes "Operators are clients of the Kubernetes API that act as controllers for a Custom Resource". 
The operator introduces a SparkApplication object kind that can be specified in a yaml file and applied using kubectl.
The corresponding controller creates the SparkApplication resource by calling `spark-submit`.
So under the hood, the operator simply uses the above described native Spark on K8s, but simply wraps it in the Kubernetes-integrated API.
It can easily be installed through Helm. 
By design, the Spark Operator doesn't support client mode, because the one who calls spark-submit is the SparkApplication controller. 
Client-mode-like applications, e. g. the REPL, can still simply bypass the operator using `--master k8s://https://...`.

## Spark Standalone on Kubernetes
A bit oxymoronically, one can also deploy Spark as _Spark Standalone on Kubernetes_, e. g. using the bitnami/spark or stable/spark Helm charts. This has been the way to go for deploying on Kubernetes before there was native support. Instead of installing Spark Standalone on a group of EC2 instances, one would virtualize the instances as containers running on Kubernetes. In so doing, one would spark-submit with `--master spark://` to a Spark Standalone Master which would then spawn executors on containerized worker nodes. Because Spark Standalone simply works with the nodes that have been registered, it is not possible to directly request new resources for a given job. Instead, scaling [is generally based on CPU and memory utilization](https://github.com/bitnami/charts/blob/master/bitnami/spark/templates/hpa-worker.yaml). In contrast to native K8s support, where the container is created on-demand using the container image given as a parameter to `spark-submit`, thus allowing to adapt executor context to the specific application, in Spark Standalone on Kubernetes, all applications share the same pre-deployed workers. The figure below summarizes the different deployment styles.

![](fig-spark-on-k8s-comparison.png)


# The Spark Container Image

## Overview
The main reason to operator Spark on Kubernetes is that that the Worker and the Master nodes are containerized. 

There are two alternatives: Either building the image ourself, or using an already published image. 

As said above, the images corresponding to the Helm charts of bitnami/spark (https://hub.docker.com/r/bitnami/spark/, [Dockerfile](https://github.com/bitnami/bitnami-docker-spark/blob/master/3/debian-10/Dockerfile)) and stable/spark image (k8s.gcr.io/spark:1.5.1_v3) are meant for Spark Standalone on K8s deployments. 
However, the gcr.io/spark-operator/spark-py:v3.0.0 from the spark-operator image repo ([Registry Repo](https://console.cloud.google.com/gcr/images/spark-operator/GLOBAL), Dockerfile built using the official Spark [Dockerfile for Kubernetes](https://github.com/apache/spark/blob/master/resource-managers/kubernetes/docker/src/main/dockerfiles/spark/Dockerfile)) is meant for K8s-native deployments. Even though it bears the name spark-operator in its tag, it is a bog-standard Spark image. 
Unfortunately, the dependencies it carries are not the newest (it features the Hadoop libraries in version 2.7.4) and it also doesn't come with libraries, we most certainly will need (e. g. in order to interact with AWS S3). 

The main problem of older versions in the container, is that your local brew-installed Spark installation may contain libraries in a more recent version (as is the case for me).
This means, that there most certainly will arise runtime errors when deploying in client mode (because the driver and the executors run different Spark versions).

Therefore, there are three alternatives: 
1. Don't use client mode (this also means: don't use the REPL or Jupyter locally which require client mode)
2. "Turn the knob on the executor side" by building a custom image
3. "Turn the knob on the driver side" by ensuring you have the same dependencies as the executors.

Alternative 1 is highly dissatisfying and makes developing slow.
Alternative 3 seems wrong (how would you get the exact same dependencies on your machine?). 

Therefore, we go to Alternative 2. And rightly so: Because, with native K8s support, we can decide on the image to employ on a per-application basis, each developer can simply bake his local Spark version into a custom image which then gets deployed. Of course, for a stable CI/CDable production, this could also happen in a build runner.

## Custom Spark Base Image Build
Therefore, let's build the PySpark image from scratch. Actually, not really from scratch, because we use the [Dockerfile for Kubernetes]((https://github.com/apache/spark/blob/master/resource-managers/kubernetes/docker/src/main/dockerfiles/spark/Dockerfile)) maintained by the Spark community, and because we use the [Docker image tool](https://github.com/apache/spark/blob/master/bin/docker-image-tool.sh) to create the build context from a local Spark distribution. 

This could be dedicated Spark distribution, built from source using the
[build](https://github.com/apache/spark/blob/master/build/mvn) and [distribution](https://github.com/apache/spark/blob/master/dev/make-distribution.sh) scripts. This is the way to go when using a dedicated build runner or maybe a Docker multi-stage build. Then, we could also maintain our dependencies in the dependency config. 

The standard Spark distribution, however, comes without S3 support, which depends on `hadoop-aws` package. Normally, we would have to add this dependency into the Maven dependency config, but because we're not building from source, we have to add it manually. It can be found in the Maven repo. The library needs to be in the same version as all other Hadoop libraries in the Spark distribution. 

Running 
```sh
export SPARK_HOME=/usr/local/Cellar/apache-spark/3.0.1/libexec
ls $SPARK_HOME/jars/" |grep hadoop
```
reveals that the Hadoop libs in version 3.2.0 are used. The package page (https://mvnrepository.com/artifact/org.apache.hadoop/hadoop-aws/3.2.0) shows that it this depends on the `AWS Java SDK Bundle` in version 1.11.375. Older Hadoop AWS libs instead depend on the `AWS Java SDK`. So, one has to be careful here when adding these to $SPARK_HOME/jars.

We build the Spark Base-Docker file
```sh
export REPO=mokari94
export SPARK_HOME=/usr/local/Cellar/apache-spark/3.0.1/libexec
cd $SPARK_HOME
bin/docker-image-tool.sh -r $REPO/spark-base -t latest -p ./kubernetes/dockerfiles/spark/bindings/python/Dockerfile build
```
This will build a pure spark image without any application-specific code tagged `$REPO/spark-base/spark:latest` and `$REPO/spark-base/spark-py:latest`. Because we're interested in spark-py only, let's use the latter. Unfortunately, while it works with AWS ECR, pushing the latter to Docker Hub fails with this tag, maybe due to the slash in the image name. 

Retagging works:
```sh
docker tag $REPO/spark-base/spark-py:latest $REPO/spark-base:latest
docker push $REPO/spark-base:latest
```

This is already a functioning Spark image. We could spawn it up and run a built-in example program that's already in the container (indicated by `local://`).

```sh
# Make sure there is a role the Submission Client can use to create our resources on the cluster.
# While this spec stems from the Operator repo, it is not specific to the Operator. 
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/spark-on-k8s-operator/master/manifest/spark-rbac.yaml

export IMAGE=mokari94/spark-base:latest
export K8S_API_URL=https://127.0.0.1:32776
spark-submit \
  --master k8s://$K8S_API_URL \
  --conf spark.kubernetes.container.image=$IMAGE \
  --conf spark.kubernetes.authenticate.driver.serviceAccountName=spark \
  --conf spark.kubernetes.container.image.pullPolicy=Always \
  --deploy-mode cluster \
  local:///opt/spark/examples/src/main/python/pi.py
```

However, as one can see, we launch a driver program that is located in the container's file system. While there is support to distribute an application that is local to the submission client (e. g. on the developer machine) [trough an S3-compatible object store](https://spark.apache.org/docs/latest/running-on-kubernetes.html#dependency-management), it is not [yet?](https://issues.apache.org/jira/browse/SPARK-27936) possible to [directly distribute the local application through Kubernetes]((https://docs.google.com/document/d/1peg_qVhLaAl4weo5C51jQicPwLclApBsdR1To2fgc48/edit)). 
 

## Custom Spark Application Image
However, the idea of Spark on Kubernetes is, that we can deploy Spark applications as containers themselves. 

So, let's already derive a custom Application container with the following properties:
- Use a Custom Python App with Custom Dependencies
- PySpark instead of Spark
- Write the result to AWS S3
- Sleep before shutting down the driver so we can have a look at the Driver UI

First, let's use the pi.py example as a starting point:
```sh
mkdir app && cd app
wget https://raw.githubusercontent.com/apache/spark/master/examples/src/main/python/pi.py
mv pi.py app.py
```

Replace the line `print("Pi is roughly %f" % (4.0 * count / n))` towards the end of the script with all of the following lines:
```py
# ...
pi_approx = 4.0 * count / n

print("Pi is roughly %f" % pi_approx)

print("Writing file to S3...")
spark \
    .createDataFrame([
        pi_approx
    ],
    "float") \
    .write \
    .mode("overwrite") \
    .csv("s3a://spark-mo/pi/")

print("Wrote file to S3...")

print("Reading file from S3...")
lines = spark \
    .read \
    .text("s3a://spark-mo/pi/") \
    .show()

print("Read file from S3!")

time.sleep(60)
```

Let's bake this into our Spark App image:
```Dockerfile
# Tag: mokari94/spark-app:latest
FROM mokari94/spark-base:latest

WORKDIR /opt/spark/work-dir
COPY app.py app.py

ENTRYPOINT [ "/opt/entrypoint.sh" ]
```

Now build and push this image to a public Docker hub (we could also use a private registry and populate a Pull secret in the next step):
```sh
export REPO=mokari94
docker build -t $REPO/spark-app:latest .
docker push $REPO/spark-app:latest
```

Alternatively, we could build the docker container **on the virtualized Minikube node** so that the Minikube Kubernetes will find the image using `eval $(minikube docker-env) && docker build -t spark-app .´ Remember to run `eval $(minikube docker-env)` whenever you enter a fresh terminal window, if you want to update the Docker image. Be careful, to set the imagePullPolicy in the next step correctly.


# Running Custom Spark Applications and Notebooks on K8s

## Prerequisites
So now, all we have done is building a custom Spark application image. However, before we can run it, we need to make sure 
- there is a Spark service account the driver can assume to create the executor pods, 
- there in an S3 bucket and prefix for the executor-created log files, so we can inspect what Spark is doing, 
- there are credentials for AWS accessible to the driver and the executors through Kubernetes Secrets, so the log files can be dumped to S3, and, in particular, so that we can read and write our data from and to S3. 

### Role

To create the service account for spark, we can reuse a spec, by the Spark operator. It has nothing to do with the operator in specific:s

```sh
kubectl apply -f https://raw.githubusercontent.com/GoogleCloudPlatform/spark-on-k8s-operator/master/manifest/spark-rbac.yaml
```

In the spark-submit call, we will indicate the service account as follows:

```sh
--conf spark.kubernetes.authenticate.driver.serviceAccountName=spark
```

### Log files

Let's create the Spark log path. We must make sure that there is at least a single file under the prefix we use (otherwise we get a FileNotFound exception in some situations, esp. when, later on, using the History Server). Assuming you've set up your AWS CLI, run: 
```sh
aws s3 mb s3://spark-mo/
touch dummy
aws s3 cp dummy s3://spark-mo/history-server/
```

In the spark-submit call, we will indicate the log args as follows:

```sh
--conf spark.eventLog.enabled=true \
--conf spark.eventLog.dir=s3a://spark-mo/history-server/
```

### Secrets

We populate the credentials from a Kubernetes secret into the container using environment variables [Spark feature](https://spark.apache.org/docs/latest/running-on-kubernetes.html#secret-management). The above notation says to populate the `aws-access-key` value from the `aws-secrets` Kubernetes secret into an environment variable called `AWS_ACCESS_KEY_ID`. Should your AWS account rely temporary role session tokens, this also could be taken into account here. In order to store the secrets as a Kubernetes secret, Put the AWS_ACCESS_KEY_ID into a file named `aws-access-key` and the AWS_SECRET_KEY into a file named `aws-secret-key`.
Make sure that there is not trailing line break.

```sh
kubectl create secret generic aws-secrets --from-file=aws-access-key --from-file=aws-secret-key
```

In the spark-submit call, we will indicate the secrets as follows:

```sh
--conf spark.kubernetes.driver.secretKeyRef.AWS_ACCESS_KEY_ID=aws-secrets:aws-access-key \
--conf spark.kubernetes.driver.secretKeyRef.AWS_SECRET_ACCESS_KEY=aws-secrets:aws-secret-key \
--conf spark.kubernetes.executor.secretKeyRef.AWS_ACCESS_KEY_ID=aws-secrets:aws-access-key \
--conf spark.kubernetes.executor.secretKeyRef.AWS_SECRET_ACCESS_KEY=aws-secrets:aws-secret-key
```

However, for the Hadoop AWS and the library , we included in our Spark Base Image, to find be able to actually make requests to the AWS API, we need to indiated the region, your bucket was created. Also, the data center I use, Frankfurt, only offers the newer v4 Authentication Signature (v2 is legacy, anyways). Therefore, we also need to set the extra java options for driver and executor. Otherwise, we'll get a very non-specific Bad Request error. Finally, we need to set the AWS credentials. 

```sh
--conf spark.hadoop.fs.s3a.endpoint=s3.eu-central-1.amazonaws.com \
--conf spark.executor.extraJavaOptions=-Dcom.amazonaws.services.s3.enableV4=true \
--conf spark.driver.extraJavaOptions=-Dcom.amazonaws.services.s3.enableV4=true
```


## Submitting Applications in Cluster Mode

Finally, let's get to action:
```sh
export IMAGE=mokari94/spark-app:latest
export K8S_API_URL=https://127.0.0.1:32776
spark-submit \
    --master k8s://$K8S_API_URL \
    --conf spark.kubernetes.authenticate.driver.serviceAccountName=spark \
    --conf spark.kubernetes.container.image=$IMAGE \
    --conf spark.kubernetes.container.image.pullPolicy=Always \
    --conf spark.executor.instances=2 \
    --conf spark.executor.cores=1 \
    --conf spark.task.maxFailures=3 \
    --conf spark.executor.memory=1g \
    --conf spark.driver.memory=1g \
    --conf spark.kubernetes.driver.secretKeyRef.AWS_ACCESS_KEY_ID=aws-secrets:aws-access-key \
    --conf spark.kubernetes.driver.secretKeyRef.AWS_SECRET_ACCESS_KEY=aws-secrets:aws-secret-key \
    --conf spark.kubernetes.executor.secretKeyRef.AWS_ACCESS_KEY_ID=aws-secrets:aws-access-key \
    --conf spark.kubernetes.executor.secretKeyRef.AWS_SECRET_ACCESS_KEY=aws-secrets:aws-secret-key \
    --conf spark.hadoop.fs.s3a.endpoint=s3.eu-central-1.amazonaws.com \
    --conf spark.executor.extraJavaOptions=-Dcom.amazonaws.services.s3.enableV4=true \
    --conf spark.driver.extraJavaOptions=-Dcom.amazonaws.services.s3.enableV4=true \
    --conf spark.eventLog.enabled=true \
    --conf spark.eventLog.dir=s3a://spark-mo/history-server/ \
    --deploy-mode cluster \
    local:///opt/spark/work-dir/app.py
```

After submitting you application, you can easily observe driver and executor creation through the Kubernetes dashboard (``minikube dashboard``) and follow the log output. The driver's log looks this:

![](fig-spark-operator-result-log.png)

In S3, under `s3a://spark-mo/pi/` (hard-coded into the application), there should be a new or updated set of result CSVs and an empty _SUCCESS flag file. Also, under `s3a://spark-mo/history-server/` (specified in the spark-submit call through `--conf spark.eventLog.dir`) there a should be new log-file. We could, of course pass the output S3 path [as an environment variable]((https://spark.apache.org/docs/latest/running-on-kubernetes.html#container-spec)) using `--spark.kubernetes.driverEnv.[EnvironmentVariableName]`.

Because this spark-submit call is a bit bulky, we shorten it a bit using a properties file, e. g. named spark-app.conf:

```conf
spark.kubernetes.authenticate.driver.serviceAccountName         spark
spark.kubernetes.container.image                                mokari94/spark-app:latest
spark.kubernetes.container.image.pullPolicy                     Always
spark.executor.instances                                        2
spark.executor.cores                                            1
spark.task.maxFailures                                          3
spark.executor.memory                                           1g
spark.driver.memory                                             1g
spark.kubernetes.driver.secretKeyRef.AWS_ACCESS_KEY_ID          aws-secrets:aws-access-key
spark.kubernetes.driver.secretKeyRef.AWS_SECRET_ACCESS_KEY      aws-secrets:aws-secret-key
spark.kubernetes.executor.secretKeyRef.AWS_ACCESS_KEY_ID        aws-secrets:aws-access-key
spark.kubernetes.executor.secretKeyRef.AWS_SECRET_ACCESS_KEY    aws-secrets:aws-secret-key
spark.hadoop.fs.s3a.endpoint                                    s3.eu-central-1.amazonaws.com
spark.executor.extraJavaOptions                                 -Dcom.amazonaws.services.s3.enableV4=true
spark.driver.extraJavaOptions                                   -Dcom.amazonaws.services.s3.enableV4=true
spark.eventLog.enabled                                          true
spark.eventLog.dir                                              s3a://spark-mo/history-server/
```

and adapt spark-submit as follows:

```sh
export K8S_API_URL=https://127.0.0.1:32776
spark-submit \
    --master k8s://$K8S_API_URL \
    --properties-file spark-app.conf \
    --deploy-mode cluster \
    local:///opt/spark/work-dir/app.py
```


Doing the same thing through the operator is straight-forward. Helm-install it, manually translate your the spark-app.conf into a Kubernetes-Manifest spark-app.yaml and run `kubectl apply spark-app.yaml` which will, under the hood, do the same thing, we just did above.

## Running Notebooks in Client Mode

### Overview
Remember that now it is important to have the same Spark distribution on your Notebook server (in this case, your developer as on the executors).
We ensured this by building our local distribution into the Spark Base Image. 

The more production-ready alternatives would be either

1. to clone the Spark repo, 
2. build a Spark distribution from source, 
3. build a Spark Base Docker image using this Spark distribution, and
4. running this specific distribution on the developer machine, 

or - for a more platformy solution - to do step 1-3 from above and instead of running on the developer machine

1. build a Notebook image based on the Spark Base Docker, 
2. launch the Notebook image in the K8s cluster running Spark on K8s in the same clster in client mode as container in a pod alongside a proxy sidecar, and 
3. expose a Notebook service to the outside.

However, for the moment, let's go with the original setup where typing `realpath $(which spark-submit)` on the will show the path to the same Spark distribution that was built into the Spark Base image. While Spark itself is written in Scala and compiled to bytecode that is always executed in a JVM, PySpark is a Python application that exposes a Python API wrapping the Java API used to communicate with the JVM. It is essential that not only the driver's and executor's Spark environment in terms of version of dependency, but also the Python environment.

So, let's make sure we're running the same Python environment as in the container. 

```sh
cat <<EOF > env.yml
name: python3.7-spark
dependencies:
  - python=3.7
  - jupyter
  - notebook
EOF

conda env update -f env.yml

python -m ipykernel install --user --name python3.7-spark
```

### REPL Shell

When running the driver on the cluster, Kubernetes will make sure that the secrets defined in Spark submit are populated to the driver. 
Now that we're controlling the driver ourselves, we need to populate the secrets ourselves.
To make sure, the executors run python3, set the env var `PYSPARK_PYTHON=python3`.
Now, let's see if our local developer machine can play the same role as a driver on the cluster:

```sh
source activate python3.7-spark
export AWS_ACCESS_KEY_ID=$(cat ../aws-access-key)
export AWS_SECRET_ACCESS_KEY=$(cat ../aws-secret-key)
export K8S_API_URL=https://127.0.0.1:32776
PYSPARK_PYTHON=python3 spark-submit \
    --master k8s://$K8S_API_URL \
    --properties-file spark-app.conf \
    --deploy-mode client \
    app.py
```

This should behave exactly like it did on the driver pod previously.

However, we actually don't want to submit a ready application, but instead run an interactive driver program. 
There, instead of  spark-submit, we use `pyspark` (the equivalent in Scala is more meaningfully called _spark-shell_). 
This will always run in client mode, however - by default - run a REPL shell. 

```sh
source activate python3.7-spark
export AWS_ACCESS_KEY_ID=$(cat ../aws-access-key)
export AWS_SECRET_ACCESS_KEY=$(cat ../aws-secret-key)
export K8S_API_URL=https://127.0.0.1:32776
PYSPARK_PYTHON=python3 pyspark \
    --master k8s://$K8S_API_URL \
    --properties-file spark-app.conf
```

It should look something like this:

![](fig-spark-on-k8s-repl.png)

### Jupyter Notebook
Finally, let's run this in Jupyter by instructing pyspark through environment variables to use run `jupyter` and pass the `notebook .` args:
```sh
source activate python3.7-spark
export AWS_ACCESS_KEY_ID=$(cat ../aws-access-key)
export AWS_SECRET_ACCESS_KEY=$(cat ../aws-secret-key)
export K8S_API_URL=https://127.0.0.1:32776
PYSPARK_PYTHON=python3 PYSPARK_DRIVER_PYTHON=jupyter PYSPARK_DRIVER_PYTHON_OPTS="notebook ." pyspark \
    --master k8s://$K8S_API_URL \
    --properties-file spark-app.conf
```

Create a new notebook with as `python3.7-spark` as an environment.

Copy the following into a cell and run it:
```py
sc.setLogLevel("INFO")

import sys
from random import random
from operator import add

import time

from pyspark.sql import SparkSession

partitions = 5
n = 1000 * partitions

print("Doing n iterations: ", n)

def f(_):
    x = random() * 2 - 1
    y = random() * 2 - 1
    return 1 if x ** 2 + y ** 2 <= 1 else 0

count = spark.sparkContext.parallelize(range(1, n + 1), partitions).map(f).reduce(add)

pi_approx = 4.0 * count / n

print("Pi is roughly %f" % pi_approx)

print("Writing file to S3...")
spark \
    .createDataFrame([
        pi_approx
    ],
    "float") \
    .write \
    .mode("overwrite") \
    .csv("s3a://spark-mo/pi/")

print("Wrote file to S3...")

print("Reading file from S3...")
lines = spark \
    .read \
    .text("s3a://spark-mo/pi/") \
    .show()

print("Read file from S3!")
```

As seen below, _print_ statements are displayed in the notebook but the driver log is given in the terminal window. 

![](fig-spark-on-k8s-jupyter.png)

Notice, that the code from within the Jupyter notebook is now actually marshaled and sent over to the executors on the cluster. 
Of course, if you now depend on a package in your Python code, it has to be part of the Spark App container so each executor can use it.
The dirtiest of dirty approaches - however proofing the technical point here - is that you could exec into your executor containers and retrofit them live in the container.
Of course, this because unwieldy if you use hundreds of executors on a large cluster and probably won't work in a production setting with permissions and stuff. 
And why should it?
Simply kill the Jupyter kernel, build the dependency into the Spark App image, publish it, and restart PySpark.

![](fig-spark-on-k8s-dirty.png)


Also note, that now, since - the driver is running on the developer machine, with further ado, you can check the driver's Spark UI, by default running on http://localhost:4040/.

Alternative to the `pyspark` command, after starting a blank notebook, one could use
```py
from pyspark import SparkConf, SparkContext
conf = SparkConf()
conf.setMaster("k8s://...")
# conf.set("...", "...")

SparkContext(conf=conf)
``` 

However, I personally prefer the CLI-based notebook startup due to its symmetry to spark-submit.

# Spark Driver UI and the History Server
By using port-forwarding, we could also check the driver's Spark UI for jobs submitted to Spark on K8s in cluster-mode. 
However the central problem is that the Spark UI is coupled to the Spark driver process, meaning that once the process ends, we the UI is no longer served.
While we can still access the raw log files themselves in the AWS S3 bucket we configure in the `spark-submit` or `pyspark` call, accessing them visually through the UI is bit more handy, isn't it.

Here, the history server comes to rescue.
It is deployed as a separate component, not necessarily but possibly on the same K8s cluster. 

In contrast to the driver UI, it's a long-running logging service that's not coupled to a specific job. Spark Drivers and Executors will send the logs to a shared file system, in our case AWS S3, which the History Server reads out and visualizes. Therefore, it is necessary that the history server as well as the driver and executors have access to the same AWS S3 bucket, so that the latters can write to it and that the former can read from it.

In theory, we can use the Spark Base image to run the History server, because we built in the dependencies (hadoop-aws and aws-java-sdk-bundle) for AWS access. 
However, it seems the history server requires to run as root. 
So, let's build and deploy an image based on the 

```Dockerfile
# Tag: mokari94/spark-history-server:latest
FROM mokari94/spark-base:latest

# Trying to run the History Server as non-root yields a LoginFailed exception on startup
# javax.security.auth.login.LoginException: java.lang.NullPointerException: invalid null input: name
USER 0

ENTRYPOINT [ "/opt/entrypoint.sh" ]
```

```sh
export REPO=mokari94
docker build -t $REPO/spark-history-server:latest .
docker push $REPO/spark-history-server:latest
```

To deploy the history server, let's use Helm. 

First, make the official Helm chart repo available.

```sh
helm repo add stable https://kubernetes-charts.storage.googleapis.com
```

Let's have a look at a config template:
```sh
helm show values stable/spark-history-server > history-server-config.yaml
```

From this, let's use the following subset:
```yaml
image:
  repository: mokari94/spark-history-server
  tag: latest
  pullPolicy: Always

environment:
  SPARK_HISTORY_OPTS:
    -Dcom.amazonaws.services.s3.enableV4=true

nfs: 
  enableExampleNFS: false

pvc: 
  enablePVC: false

s3:
  enableS3: true
  enableIAM: false
  secret: aws-secrets
  accessKeyName: aws-access-key
  secretKeyName: aws-secret-key
  logDirectory: s3a://spark-mo/history-server/
  endpoint: s3.eu-central-1.amazonaws.com
```

Now, let's deploy the history server using: 
```sh
helm install -f history-server-config.yaml spark-history-server stable/spark-history-server
```

and finally, expose it to the outside using
```sh
minikube service spark-history-server
```

![](fig-spark-on-k8s-history.png)


# Outlook
In this post, we've examined how to setup a fully Container-based, PySpark-based, History-Server-monitored workflow for submitting Spark applications and interactively running Spark-backed notebooks on Kubernetes. While I always strive to avoid trivial examples that do not capture the complexities of going to production, there are of course still quite some relaxations in the previous remarks incl. 
- not building from source and therefore relying on a highly fragile manual dependency management (it would be interesting to have a look at Docker Multistage builds for this).
- running a local Jupyter Notebook server as a Spark driver that is far away from the cluster (if not using Minkube), instead of running it at a Pod in the same cluster
- assuming a dedicated Kubernetes cluster, thus ignoring roles and the concept of Namespaces and installing everything to default,
- not detailing the use of [Databricks' Koalas library](https://github.com/databricks/koalas) for a pandas-like user experience.

In the next post, we'll see how to take everything learned so far together, to transform 1 Terabyte of the Waymo Open Dataset, consisting of 1000 Protobuf clips, to the RGB camera frames and labels only, using 150 executors running on an EKS cluster for consumption. 

![](fig-spark-on-k8s-waymo.png)
