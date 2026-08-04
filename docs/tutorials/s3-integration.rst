How to integrate with S3
========================

The SDK stores tag and semantic data in local SQLite files. Keep the engine
local and synchronize source files or library directories with S3 at the host
boundary; this avoids making database transactions depend on object-store
latency. For example, an embedding host can stage a source object, classify
it, and then upload its durable result using its existing AWS credentials::

   from pathlib import Path

   import boto3

   from unifile_sdk import Classifier, TagLibrary

   bucket = "example-library"
   key = "incoming/client-acme-q3/report.pdf"
   local_root = Path("/var/lib/unifile/staging")
   local_file = local_root / "report.pdf"
   local_file.parent.mkdir(parents=True, exist_ok=True)

   s3 = boto3.client("s3")
   s3.download_file(bucket, key, str(local_file))

   result = Classifier().classify(local_file.parent.name, str(local_file.parent))
   library = TagLibrary(str(local_root))
   library.open()
   library.add_entry(str(local_file))
   library.close()

   s3.upload_file(str(local_file), bucket, "processed/" + key.rsplit("/", 1)[-1])

``boto3`` is intentionally not an SDK dependency. Hosts should choose their
own S3-compatible client, credential provider, retry policy, and object-key
layout. Never put access keys in library metadata or source files.
