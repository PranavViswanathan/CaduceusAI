-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Grant privileges (database already created by POSTGRES_DB env var)
GRANT ALL PRIVILEGES ON DATABASE medical_ai TO medical_user;
