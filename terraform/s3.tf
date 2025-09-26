resource "aws_s3_bucket" "raw" {
  bucket = "upcrewpro-raw"
  acl    = "private"
  server_side_encryption_configuration {
    rule {
      apply_server_side_encryption_by_default {
        sse_algorithm = "aws:kms"
        kms_master_key_id = aws_kms_key.s3_key.arn
      }
    }
  }
  versioning { enabled = true }
  tags = {
    Project = "UPCrewPro"
  }
}

resource "aws_kms_key" "s3_key" {
  description = "KMS key for S3 encryption"
}
