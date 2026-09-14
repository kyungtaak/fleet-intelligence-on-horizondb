CREATE EXTENSION IF NOT EXISTS vector CASCADE;
CREATE EXTENSION IF NOT EXISTS pg_diskann CASCADE;
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS azure_ai;

CREATE SCHEMA IF NOT EXISTS horizon_ship;

-- Records the embedding configuration expected by semantic search at startup.
CREATE TABLE IF NOT EXISTS horizon_ship.embedding_configuration (
	singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
	endpoint text NOT NULL,
	deployment text NOT NULL,
	dimensions integer NOT NULL CHECK (dimensions = 1536)
);

-- Authoritative shipment business data. Embeddings are stored separately by FK.
CREATE TABLE IF NOT EXISTS horizon_ship.shipments (
	id uuid PRIMARY KEY DEFAULT public.uuid_generate_v4(),
	shipment_number text NOT NULL UNIQUE,
	title text NOT NULL,
	description text NOT NULL,
	origin_name text NOT NULL,
	origin_position public.geometry(Point, 4326) NOT NULL,
	destination_name text NOT NULL,
	destination_position public.geometry(Point, 4326) NOT NULL,
	current_location_name text NOT NULL,
	current_position public.geometry(Point, 4326) NOT NULL,
	status text NOT NULL CHECK (
		status IN ('in_transit', 'delivered', 'delayed', 'exception', 'unknown')
	),
	eta date,
	updated_at timestamptz NOT NULL DEFAULT now(),
	metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- Outbox and azure_ai pipeline source. One row is retained per shipment.
CREATE TABLE IF NOT EXISTS horizon_ship.shipment_embedding_jobs (
	shipment_id uuid PRIMARY KEY
		REFERENCES horizon_ship.shipments(id) ON DELETE CASCADE,
	embedding_input text NOT NULL,
	content_version bigint NOT NULL CHECK (content_version > 0),
	updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
	metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
	-- azure_ai 2.2.2 requires its default output column on the source schema.
	-- This remains NULL; the generated vector is written to shipment_embeddings.
	embedding public.vector(1536)
);

-- Pipeline sink containing the current searchable vector for each shipment.
CREATE TABLE IF NOT EXISTS horizon_ship.shipment_embeddings (
	shipment_id uuid PRIMARY KEY
		REFERENCES horizon_ship.shipments(id) ON DELETE CASCADE,
	embedding_input text NOT NULL,
	content_version bigint NOT NULL CHECK (content_version > 0),
	updated_at timestamptz NOT NULL,
	metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
	embedding public.vector(1536) NOT NULL
);

-- Enqueues inserts and semantic-field changes. setup_database.py installs the
-- table trigger only after the initial backfill and DiskANN index are ready.
CREATE OR REPLACE FUNCTION horizon_ship.enqueue_shipment_embedding()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
	IF TG_OP = 'UPDATE' AND ROW(
		OLD.title,
		OLD.description,
		OLD.origin_name,
		OLD.destination_name,
		OLD.current_location_name,
		OLD.status,
		OLD.metadata
	) IS NOT DISTINCT FROM ROW(
		NEW.title,
		NEW.description,
		NEW.origin_name,
		NEW.destination_name,
		NEW.current_location_name,
		NEW.status,
		NEW.metadata
	) THEN
		RETURN NEW;
	END IF;

	INSERT INTO horizon_ship.shipment_embedding_jobs AS existing_job (
		shipment_id,
		embedding_input,
		content_version,
		updated_at,
		metadata
	)
	VALUES (
		NEW.id,
		concat_ws(
			' ',
			NEW.title,
			NEW.description,
			NEW.origin_name,
			NEW.destination_name,
			NEW.current_location_name,
			NEW.status,
			NEW.metadata::text
		),
		COALESCE((
			SELECT current_embedding.content_version + 1
			FROM horizon_ship.shipment_embeddings AS current_embedding
			WHERE current_embedding.shipment_id = NEW.id
		), 1),
		clock_timestamp(),
		jsonb_build_object('shipment_number', NEW.shipment_number)
	)
	ON CONFLICT (shipment_id) DO UPDATE SET
		embedding_input = EXCLUDED.embedding_input,
		content_version = existing_job.content_version + 1,
		updated_at = EXCLUDED.updated_at,
		metadata = EXCLUDED.metadata,
		embedding = NULL;

	RETURN NEW;
END;
$function$;

CREATE INDEX IF NOT EXISTS shipments_current_position_gix
	ON horizon_ship.shipments USING gist (current_position);
CREATE INDEX IF NOT EXISTS shipments_status_idx
	ON horizon_ship.shipments (status);

COMMENT ON TABLE horizon_ship.shipments IS
	'Shipping data combining relational fields and PostGIS locations.';
COMMENT ON TABLE horizon_ship.shipment_embedding_jobs IS
	'Pipeline source containing only shipments whose semantic search input changed.';
COMMENT ON COLUMN horizon_ship.shipment_embedding_jobs.content_version IS
	'Incremented for each semantic change; search uses only matching sink versions.';
COMMENT ON COLUMN horizon_ship.shipment_embedding_jobs.embedding IS
	'Nullable azure_ai 2.2.2 output placeholder; actual vectors are stored in shipment_embeddings.';
COMMENT ON TABLE horizon_ship.shipment_embeddings IS
	'One current text-embedding-3-small vector per shipment, populated by initial backfill or the HorizonDB AI pipeline.';
