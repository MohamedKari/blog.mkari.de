---
title: "Out-of-the-box Storage Infrastructure Alternatives for Scaled Machine Learning"
date: 2020-06-18T23:52:00+02:00
draft: True
author: Mo Kari
---

# The problem of storing large volumes of unstructured datasets
As we all know, data preprocessing is a vital part of machine learning workflow. However, the story starts even earlier. Even before versioning or labelling data, we have to store the data we want learn from. This quickly becomes a non-trivial task in deep learning problems where we often operate on non-textual data such as images resulting in terabyte-scale dataset sizes as in the [Waymo dataset](https://waymo.com/open/about/) for example. Datasets of these sizes are generally not suitable for any laptop or your internet connection. And chances are that with a dataset like this, you also plan on training your model versions across a good number of GPUs provided by some cloud vendor. The question then arises on which cloud technology to use to store your data on and how to ingest it.

This post assumes that the relevant data comes in the form of files (such as tar, zip, jpg, parquet, hdf5, tfrecord, txt, ...) as opposed to tables, streams, APIs, etc. For the sake a concrete picture, technologies are exemplified by AWS products even though the other hyperscalers provide mostly equivalent counterparts. Data versioning and access through a feature store is left for a later post.

# TL;DR
If you want to build up a good practice,
- that scales in capacity and throughput, 
- is compatible with a clean container-based MLDevOps approach,
- is cost-effective,
- allows managing access permissions and sharing, 
- is technically flexible by offering an HTTP-based REST API as well being able to be FUSE-mounted using tools such as Alluxio, MezzFS or S3FS, and 
- has broad support in ML tooling,

an object store such as S3 is your best bet. 

Sharding large datasets during preprocessing in mid-sized chunks, that are large enough to avoid HTTP connection overhead, yet numerous enough to allow being distributed across all nodes in distributed training, is good practice. Lazily streaming data in as it is needed during training (e. g. by using the tf.data API or implementing a suitable PyTorch IterableDataset & DataLoader) avoids start-up delays and high-volume disk requirements, however needs careful implementation to ensure that network IO doesn't become a bottleneck.

# Alternatives of storing high-volume datasets in the cloud

## An overview 

The typical alternatives that come to mind are:

Storage Medium                  | Storage Access
--------------------------------|-------------------------------------------------------------------------------------------------------------------------
Object Storage                  |Lazily stream in data into the ML process using (e. g. using the tf.data API or a custom PyTorch IterableDataset)
Object Storage                  |Download to local (e. g. a local SSD or shm first, then train (equivalent to AWS SageMaker File Mode)
Object Storage, File Storage    |Mount with NFS or other storage-access wrappers such as Alluxio or S3FS providing a FUSE
Block Storage                   |Attach an existing block storage device it to the machine
Block Storage                   |Restore a block storage snapshot a new block storage device and attach it to the machine
Data Lake                       |Shard data across nodes and process one shard per node (e. g. using Spark and a deep-learning framework simulatenously)
Data in some Data Registry      |Technically one of the above

## Block Storage
Block-storage devices comprise SSDs and HDDs. In the hyperconvergent world, we have to differentiate between machine-local devices that are physically co-located with the computer and persistent devices that accessed through a storage area network. While machine-local SSDs are transient in a sense that the data stored on disk is lost after crashing the machine and the device is not re-attachable to any other machine through an API, persistent SSDs are accessed through some form of network which allows attaching it to multiple instances either simulatenously or over time. However, even though persistent disks can be shared a low number of multiple machines in read-only mode, having multiple processes read training samples from a single disk will obviously create a bottleneck. A better approach could be to snapshot the disk once we acquired the dataset, e. g. downloaded it, and thus allowing us to restore the snapshot to a new disk upon VM creation. [Some large datasets](http://millionsongdataset.com/pages/getting-dataset/) are distributed this way, however this approach 
- will limit us to the specific cloud provider and its mechanisms for mounting the volume (e. g. prohibiting us to use Google Colab or accessing at least a subset of the data locally), 
- won't allow us to access the data inside a non-privileged Docker container, 
- has a considerable amount of lead time, since restoring the snapshot means that the corresponding data will be downloaded from S3 to the drive under the hood, (stored in S3, by the way), and 
- means that managing versions is a mess, esp. in a setting with multiple people. 

## File Storage, Object Storage, and File Storage vs. Object Storage
File-storage in the cloud basically means network-attached storage (NAS) where this storage is provided by a distributed file systes. This includes AWS EFS, HDFS, Lustre, GlusterFS and CephFS for example. It accessed by mounting the storage logically into the OS file system so that it can be seamlessly accessed as if it were local while actually being reading and writing over the network. 

On the other hand, object storage is accessed through HTTP Requests to a REST API (or SDKs wrapping access to the API) on a per-object basis making it very easy to be called from any system. You can easily generate download links for objects, diff and sync local folders with the objects in the bucket or filter by the object key. With its HTTP-based interface, object storage is a perfect fit for containerized workflows while NFS mounts require priviledged container mode.

Both technologies are highly scalable, for the purposes I have been dealing virtually unlimited, when it comes capacity and aggregate throughput. It's single-file access and the client side's processing or networking capacity we have to worry about.

With respect to S3, assuming
- you have enough CPU cores, 
- you don't have a local bottleneck (such as local disk or a GPU that has to process all the data),
- you're transfering large files so that HTTP connection overhead is low, and
- your instance type's bandwith is high enough,
network transfer between an EC2 instance and S3 is officially indicated with an insane level of 3 GB/s[^aws_ec2_to_s3] of aggregate bandwidth, meaning you can transfer a terabyte worth of data in 5 minutes. However, these speeds can only be achieved using multiple network threads, e. g. somewhere between 10 and 30, handling different downloads, while with a single thread handling a single connection, speed will peak at about 100 to 200 MB/s[^s3_benchmark]. So, unlessing spending your first hours of your data science project on parallelizing your download setup, that is the speed you should bank on. 

In theory, EFS also offers multiple GB/s throughput, however in the cheapest payment plan its throughput depends on the size of the data store and, e. g. for file systems storing up to 1TB, is limited at 100 MB/s[^efs]. But in addition to being half as fast, for a 1TB dataset, storage is an order of magnitude more expensive. And further more, after using up the so-called EFS bursting credits, speed is further throttled unless paying extra. 

If FUSE-mounted through third-party tools such as [Alluxio](https://docs.alluxio.io/os/user/stable/en/Overview.html), [MezzFS](https://netflixtechblog.com/mezzfs-mounting-object-storage-in-netflixs-media-processing-platform-cda01c446ba)[^mezzfs], or [S3FS](https://github.com/s3fs-fuse/s3fs-fuse), S3 can be used similarly to EFS or HDFS from an interface point-of-view (also covering important details such as caching), yet it offers a much better cost effectiveness while at the same time providing the S3 API for free on top so to speak.

However, both EFS and S3 will yield dramatically worse tranfers rates when syncing a directoy with tens of thousands of small-sized images from or to local because a single HTTP request will be made for each single file to transferred. Therefore, no matter whether EFS or S3 is used, it makes most sense, to store datasets consisting of many small files such as images in an archive format (e. g. tar, zip, tfrecord, parquet). 

Furthermore, it should be noted that accessing files through the network as they are needed - no matter whether mounted or by means of an REST API or SDK - will definitely yield worse results than accessing a machine-local SSD if no countermeasures are taken. First, time-to-first-byte latency considerably increases. Second, downloading the file containing the next batch might be slower than processing it, esp. when using multiple GPUs. Third, the CPU might also have to handle TLS decryption and possibly deserialization [^tf_data]. One solution could be to simply syncing data to a fast machine-local SSD before preprocessing or training and syncing resulting feature data or artifacst back to the remote storage. However, obviously this introduces a significant lead time before the actual processing step starts. Furthermore, it requires a large locally attached volume instead of a networked volume. Elsewise, one is copying from network to network not solving any problem. Thus, a dedicated data ingestion library such as [tf.data](https://www.tensorflow.org/guide/data) which supports prefetching samples and parallelizing dataset loading from local file systems (or mounts) as well as S3-compliant object stores (and also HDFS) is a neat and reusable approach.

## Data-Lake Storage
Even though there are some efforts [^sparktorch] [^databricks_horovod], I have not seen much attention going to exploiting data-lake architectures with co-located compute and storage for distributed training. While this seems to be an interesting approach, the problem of not being able to scale compute and storage separately, esp. when requiring expensive GPU machines, might be the reason. However if using, for example, an Hadoop cluster for only storing the data but not processing it, then one is basically throwing any advantage over an object storage solution away leaving only disadvantages. 

# Conclusion
When selecting between these different alternatives, for a one-off project properties of the use case such as 
- requirements by an existing codebase,
- containerization of the ML workflow,
- multi-node or multi-GPU requirement,
- data subset selection based on metadata,
- number of trainings epochs,
- production-grade requirement,
- dataset size,
- collaboration requirement, 
- framework usage,
- deployment model,
- data evolution, 
- neighboring data and application landscape, and of course
- budget,

might be relevant. 

However, if you are thinking through these things, chances are you are doing more than a sole ML project in your life. But having multiple ways in place to achieve the same things is something your time is not worthy of. Therefore, unless having good and explicit reasons in a specific situation against them, object stores seem to be the best way  to go. 

[^aws_ec2_to_s3]: https://aws.amazon.com/blogs/aws/the-floodgates-are-open-increased-network-bandwidth-for-ec2-instances/
[^s3_benchmark]: https://github.com/dvassallo/s3-benchmark
[^sparktorch]: https://github.com/dmmiller612/sparktorch
[^databricks_horovod]: https://docs.databricks.com/applications/deep-learning/distributed-training/horovod-runner.html#horovodrunner
[^efs]: https://docs.aws.amazon.com/efs/latest/ug/performance.html 
[^tf_data]: https://www.tensorflow.org/guide/data_performance#parallelizing_data_extraction
[^mezz_fs]: Thanks to [Tobias Grosse-Puppendahl](http://www.grosse-puppendahl.com/) for the tip.
