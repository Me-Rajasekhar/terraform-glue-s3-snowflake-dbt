-- snowflake/sql/02_create_file_format_and_stage.sql
CREATE OR REPLACE FILE FORMAT UPCREWPRO.PUBLIC.FILE_FORMAT_PARQUET
  TYPE = 'PARQUET'
  COMPRESSION = 'AUTO';
-- Note: Use STORAGE INTEGRATION for production. Placeholder below:
-- CREATE OR REPLACE STORAGE INTEGRATION my_integration ... ;
