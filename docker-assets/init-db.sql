-- Create database if it doesn't exist
DO $$ 
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_database 
      WHERE datname = 'adtestpro_oss'
   ) THEN
      CREATE DATABASE adtestpro_oss;
   END IF;
END
$$;

-- Create the adtestpro role with password if it doesn't exist
DO $$
BEGIN
   IF NOT EXISTS (
      SELECT FROM pg_catalog.pg_roles 
      WHERE rolname = 'adtestpro'
   ) THEN
      CREATE ROLE adtestpro WITH LOGIN PASSWORD 'adtestpro';
   END IF;
END
$$;

-- Grant necessary permissions to adtestpro
GRANT ALL PRIVILEGES ON DATABASE adtestpro_oss TO adtestpro;

-- Connect to the adtestpro_oss database
\c adtestpro_oss;

-- Grant schema permissions to adtestpro
GRANT ALL ON SCHEMA public TO adtestpro;
