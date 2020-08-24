---
title: "Out-of-the-box Storage Infrastructure Alternatives for Scaled Machine Learning"
date: 2020-06-20
draft: false
author: Mo Kari
---

# The problem of storing large volumes of unstructured datasets
Data preprocessing is a vital part of machine learning workflows. However, the story starts even earlier. Even before versioning or labelling data, we have to store the data we want learn from. This quickly becomes a non-trivial task in deep-learning problems where we often operate on non-tabular data such as images resulting in terabyte-scale dataset sizes such as the [Waymo dataset](https://waymo.com/open/about/) for example. Datasets of these sizes are generally not suitable for any laptop or your home internet connection. And chances are that with a dataset like this, you also plan on training your model versions across a good number of GPUs provided by some cloud vendor. The question then arises which cloud technology to use to store your data on and how to ingest it.

This post assumes that the relevant data comes in the form of files (such as tar, zip, jpg, parquet, hdf5, tfrecord, txt, ...) as opposed to tables, streams, APIs, etc. For the sake a concrete picture, technologies are exemplified by AWS products even though the other hyper-scalers provide mostly equivalent counterparts. Data versioning and data access through a feature store is left for a later post.

# TL;DR
If you want to build up a good practice
- that scales in capacity and throughput, 
- is compatible with a clean container-based MLDevOps approach,
- is cost-effective,
- allows managing access permissions and data sharing, 
- is technically flexible by offering an HTTP-based REST API as well being able to be FUSE-mounted using tools such as Alluxio or S3FS, and 
- has broad support in ML tooling,

an object store such as S3 is your best bet. 

Sharding large datasets during preprocessing in mid-sized chunks, that are large enough to avoid HTTP connection overhead, yet numerous enough to allow being distributed across all nodes in distributed training, is good practice. Lazily streaming data in as it is needed during training (e. g. by using the tf.data API or implementing a suitable PyTorch IterableDataset) avoids start-up delays and high-volume disk requirements, however needs careful implementation to ensure that network IO doesn't become a bottleneck.

# Alternatives of storing high-volume datasets in the cloud

## An overview 

The typical alternatives that come to mind are:

Storage Medium                  | Storage Access
--------------------------------|-------------------------------------------------------------------------------------------------------------------------
Object Storage                  |Lazily stream in data into the ML process (e. g. using the tf.data API or a custom PyTorch IterableDataset)
Object Storage                  |Download to local (e. g. a local SSD or shm) first, then train (equivalent to AWS SageMaker File Mode)
Object Storage, File Storage    |Mount with NFS or other storage-access wrappers such as Alluxio or S3FS providing a FUSE
Block Storage                   |Attach an existing block storage device to the machine
Block Storage                   |Restore a block storage snapshot to a new block storage device and attach it to the machine
Data Lake                       |Shard data across nodes and process one shard per node (e. g. using Spark and a deep-learning framework simultaneously)
Data in some Data Registry      |Technically one of the above

## Block Storage
Block-storage devices comprise SSDs and HDDs. In the hyperconvergent world, we have to differentiate between machine-local, direct-attached devices that are physically co-located with the computer, and persistent devices that accessed through a storage area network. While machine-local SSDs are transient in a sense that the data stored on disk is lost after crashing the machine and in that it is not re-attachable to any other machine through an API, persistent SSDs are accessed through some form of network which allows attaching it to multiple instances either simultaneously or over time. However, even though persistent disks can be shared a low number of multiple machines in read-only mode, having multiple processes read training samples from a single disk will obviously create a bottleneck. A better approach could be to snapshot the disk once we acquired the dataset, e. g. downloaded it, and thus allowing us to restore the snapshot to a new disk upon VM creation. [Some large datasets](http://millionsongdataset.com/pages/getting-dataset/) are distributed this way, however this approach 
- will limit us to the specific cloud provider and its mechanisms for mounting the volume (e. g. prohibiting us to use Google Colab or accessing at least a subset of the data locally), 
- won't allow us to access the data inside a non-privileged Docker container, 
- has a considerable amount of lead time, since restoring the snapshot means that the corresponding data will be downloaded from S3 to the SSD drive and de-archived there under the hood, and 
- means that managing versions is a mess, esp. in a setting with multiple people. 

## File Storage, Object Storage, and File Storage vs. Object Storage
File-storage in the cloud basically means network-attached storage (NAS) where this storage is provided by a distributed file system. This includes AWS EFS, HDFS[^hdfs], Lustre, GlusterFS and CephFS[^ceph] for example. It is accessed by mounting the storage logically into the OS file system so that it can be seamlessly read from and written to as if it were local while actually being read from and written to over the network[^nfs]. 

On the other hand[^adls], object storage such as S3 or Minio is accessed through HTTP requests to a REST API (or SDKs wrapping access to the API) on a per-object basis making it very easy to be called from any internet-connected system. You can easily generate download links for objects, diff and sync local folders with the objects organized in the bucket or filter by object key. With its HTTP-based interface, object storage is a perfect fit for containerized workflows while NFS mounts require privileged container mode [^privileged_mode].

Both technologies are highly scalable - for the purposes I have been dealing virtually unlimited - when it comes capacity and aggregate throughput. Instead it's single-file access and the client side's processing or networking capacity we have to worry about.

With respect to S3, assuming
- you have enough CPU cores, 
- you don't have a local bottleneck (such as local disk or a GPU that has to process all the data),
- you're transferring large files so that HTTP connection overhead is low, and
- your instance type's bandwidth is high enough,
network transfer between an EC2 instance and S3 is officially indicated with an insane level of 3 GB/s[^aws_ec2_to_s3] of aggregate bandwidth, meaning you can transfer a terabyte worth of data in 5 minutes. However, these speeds can only be achieved using multiple network threads, e. g. somewhere between 10 and 30, handling different downloads, while with a single thread handling a single connection, speed will peak at about 100 to 200 MB/s[^s3_benchmark]. 

In theory, EFS (and of course other high-performance distributed file system) also offers many GB/s throughput, however in the cheapest payment plan its throughput depends on the size of the data store and, e. g. for file systems storing up to 1TB, is limited at 100 MB/s[^efs]. But, for a 1TB dataset, storage is an order of magnitude more expensive. And furthermore, after using up the so-called EFS bursting credits, speed is further throttled unless paying extra. 

If FUSE-mounted through third-party tools such as [Alluxio](https://docs.alluxio.io/os/user/stable/en/Overview.html) or [S3FS](https://github.com/s3fs-fuse/s3fs-fuse)[^mezzfs], S3 can be used similarly to EFS or HDFS from an interface point-of-view (also covering important details such as caching), yet it offers much better cost-effectiveness while at the same time providing the S3 API for free on top so to speak.

However, both EFS and S3 will yield dramatically worse transfer rates when syncing a directory with tens of thousands of small-sized images from or to local because a single HTTP request will be made for every single file to be transferred. Therefore, no matter whether EFS or S3 is used, it makes the most sense, to store datasets consisting of many small files such as images in an archive format (e. g. tar, zip, tfrecord, parquet).

Furthermore, it should be noted that accessing files through the network as they are needed - no matter whether mounted or by means of a REST API or SDK - will definitely yield worse results than accessing a machine-local SSD if no countermeasures are taken. First, time-to-first-byte latency considerably increases. Second, downloading the file containing the next batch might be slower than processing it, esp. when using multiple GPUs. Third, the CPU might also have to decryption, decompression and possibly deserialization [^tf_data]. One solution could be to simply syncing data to a fast machine-local SSD before preprocessing or training and syncing resulting feature data or artifacts back to the remote storage. However, obviously this introduces a significant lead time before the actual processing step starts. Furthermore, it requires a large locally attached volume instead of a networked volume. Elsewise, one is copying from network to network not solving any problem. Thus, a dedicated data ingestion library such as [tf.data](https://www.tensorflow.org/guide/data) which supports prefetching samples and parallelizing dataset loading from local file systems (or mounts) as well as from S3-compliant object stores (and also HDFS) is a neat and reusable approach.

## Data-Lake Storage
Even though there are some efforts [^sparktorch] [^databricks_horovod], I have not seen much attention going to exploiting data-lake architectures with co-located compute and storage for distributed training. While this seems to be an interesting approach, the problem of not being able to scale compute and storage separately, esp. when requiring expensive GPU machines, might be the reason. However if using, for example, a Hadoop cluster for only storing the data but not processing it, then one is basically throwing any advantage over an object storage solution away leaving only disadvantages (e. g. pricing). 

# Conclusion
When selecting between these different alternatives, for a one-off project, properties of the use case such as 
- requirements by an existing codebase,
- containerization of the ML workflow,
- multi-node or multi-GPU requirement,
- data-subset selection based on metadata,
- number of training epochs,
- production-grade requirement,
- dataset size,
- collaboration requirement, 
- framework usage,
- deployment model,
- data evolution, 
- neighboring data and application landscape, and of course
- budget,

might be relevant. 

However, if you are thinking through these things, chances are you are doing more than a sole ML project in your life. But having multiple ways in place to achieve the same things is something your time is not worthy of. Therefore, unless having good and explicit reasons in a specific situation against them, object stores seem to be the best way to go. 

[^aws_ec2_to_s3]: https://aws.amazon.com/blogs/aws/the-floodgates-are-open-increased-network-bandwidth-for-ec2-instances/
[^s3_benchmark]: https://github.com/dvassallo/s3-benchmark
[^sparktorch]: https://github.com/dmmiller612/sparktorch
[^databricks_horovod]: https://docs.databricks.com/applications/deep-learning/distributed-training/horovod-runner.html#horovodrunner
[^efs]: https://docs.aws.amazon.com/efs/latest/ug/performance.html 
[^tf_data]: https://www.tensorflow.org/guide/data_performance#parallelizing_data_extraction
[^mezzfs]: Netflix seems to use a self-developed tool called [MezzFS](https://netflixtechblog.com/mezzfs-mounting-object-storage-in-netflixs-media-processing-platform-cda01c446ba) for these purposes. Thanks to [Tobias Grosse-Puppendahl](http://www.grosse-puppendahl.com/) for the tip.
[^privileged_mode]: https://docs.docker.com/engine/reference/commandline/run/#full-container-capabilities---privileged
[^hdfs]: Shvachko, Kuang, Radio, Chansler (2010). The Hadoop Distributed File System. Symposium on Mass Storage Systems and Technologies (MSST). doi:10.1109/MSST.2010.5496972.
[^adls]: ADLS does neither have an S3-like API nor does it aim at being FUSE-mounted. It is specifically designed for compute-storage colo. See Ramakrishnan et al. (2017). Azure Data Lake Store: A Hyperscale Distributed File Service for Big Data Analytics. International Conference on Management of Data (SIGMOD). doi:10.1145/3035918.3056100.
[^ceph]: Weil, Brandt, Miller, Long (2006). Ceph: A Scalable, High-Performance Distributed File System. Conference on Operating Systems Design and Implementation (OSDI). 
[^nfs]: _a classic_: Sandberg, Goldberg, Kleiman, Walsh, Lyon (1985). Design and Implementation of the Sun Network Filesystem. USENIX Conference & Exhibition.