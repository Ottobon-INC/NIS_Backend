CREATE TYPE sourcepriority AS ENUM ('P0', 'P1', 'P2');
CREATE TYPE sourcestatus AS ENUM ('ENABLED', 'DISABLED', 'UNAVAILABLE', 'REQUIRES_CONFIGURATION', 'RATE_LIMITED', 'ERROR');
CREATE TYPE evidencetype AS ENUM ('FACT', 'SIGNAL', 'INFERENCE', 'HYPOTHESIS');
CREATE TYPE contactstatus AS ENUM ('NEW', 'RESEARCHING', 'READY');
CREATE TYPE runstatus AS ENUM ('NOT_STARTED', 'QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'CANCELLED');
CREATE TYPE taskstatus AS ENUM ('PENDING', 'QUEUED', 'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'SKIPPED');

CREATE TABLE research_sources (
	id VARCHAR NOT NULL, 
	name VARCHAR NOT NULL, 
	source_type VARCHAR, 
	priority sourcepriority, 
	status sourcestatus, 
	provider_type VARCHAR, 
	description VARCHAR, 
	supported_entity_types JSON, 
	supported_intelligence_types JSON, 
	reliability_score INTEGER, 
	requires_api_key BOOLEAN, 
	requires_paid_license BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_research_sources_id ON research_sources (id);

CREATE TABLE contacts (
	id VARCHAR NOT NULL, 
	organization_id VARCHAR, 
	contact_type VARCHAR NOT NULL DEFAULT 'TARGET',
	first_name VARCHAR, 
	last_name VARCHAR, 
	full_name VARCHAR, 
	current_title VARCHAR, 
	current_company VARCHAR, 
	company_website VARCHAR,
	email VARCHAR, 
	phone VARCHAR, 
	location VARCHAR, 
	profile_url VARCHAR, 
	profile_image_url VARCHAR, 
	status contactstatus, 
	card_status VARCHAR DEFAULT 'PROCESSING',
	admin_notes TEXT,
	reviewed_by VARCHAR,
	founder_reviewed BOOLEAN DEFAULT FALSE,
	founder_notes TEXT,
	founder_reviewed_at TIMESTAMP WITH TIME ZONE,
	best_route JSONB,
	relationship_strength INTEGER,
	reachability VARCHAR,
	best_channel VARCHAR,
	relationship_notes TEXT,
	connected_since DATE,
	is_scored BOOLEAN DEFAULT FALSE,
	import_batch_id VARCHAR,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_contacts_id ON contacts (id);
CREATE INDEX ix_contacts_organization_id ON contacts (organization_id);
CREATE INDEX ix_contacts_contact_type ON contacts (contact_type);
CREATE INDEX ix_contacts_card_status ON contacts (card_status);
CREATE INDEX ix_contacts_is_scored ON contacts (is_scored);
CREATE INDEX ix_contacts_import_batch_id ON contacts (import_batch_id);

CREATE TABLE company_profiles (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	description TEXT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_company_profiles_id ON company_profiles (id);

CREATE TABLE services (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	description TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_services_id ON services (id);

CREATE TABLE products (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	description TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_products_id ON products (id);

CREATE TABLE capabilities (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	description TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_capabilities_id ON capabilities (id);

CREATE TABLE expertise (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_expertise_id ON expertise (id);

CREATE TABLE industries (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_industries_id ON industries (id);

CREATE TABLE use_cases (
	id VARCHAR NOT NULL, 
	name VARCHAR, 
	description TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_use_cases_id ON use_cases (id);

CREATE TABLE case_studies (
	id VARCHAR NOT NULL, 
	title VARCHAR, 
	content TEXT, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_case_studies_id ON case_studies (id);

CREATE TABLE external_identities (
	id VARCHAR NOT NULL, 
	contact_id VARCHAR, 
	provider VARCHAR, 
	identifier_type VARCHAR, 
	identifier VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(contact_id) REFERENCES contacts (id)
);
CREATE UNIQUE INDEX ix_external_identities_identifier ON external_identities (identifier);
CREATE INDEX ix_external_identities_id ON external_identities (id);

CREATE TABLE research_runs (
	id VARCHAR NOT NULL, 
	contact_id VARCHAR, 
	status runstatus, 
	triggered_by VARCHAR, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	error_message VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(contact_id) REFERENCES contacts (id)
);
CREATE INDEX ix_research_runs_id ON research_runs (id);

CREATE TABLE research_tasks (
	id VARCHAR NOT NULL, 
	research_run_id VARCHAR, 
	source_id VARCHAR, 
	status taskstatus, 
	priority VARCHAR, 
	target_metadata JSON, 
	started_at TIMESTAMP WITH TIME ZONE, 
	completed_at TIMESTAMP WITH TIME ZONE, 
	error_message VARCHAR, 
	retry_count INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(research_run_id) REFERENCES research_runs (id), 
	FOREIGN KEY(source_id) REFERENCES research_sources (id)
);
CREATE INDEX ix_research_tasks_id ON research_tasks (id);

CREATE TABLE source_results (
	id VARCHAR NOT NULL, 
	source_id VARCHAR, 
	research_task_id VARCHAR, 
	query VARCHAR, 
	entity_searched VARCHAR, 
	retrieved_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	raw_reference VARCHAR, 
	status VARCHAR, 
	extracted_data JSON, 
	metadata JSON, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES research_sources (id), 
	FOREIGN KEY(research_task_id) REFERENCES research_tasks (id)
);
CREATE INDEX ix_source_results_id ON source_results (id);

CREATE TABLE evidence (
	id VARCHAR NOT NULL, 
	evidence_type evidencetype, 
	claim VARCHAR, 
	source_id VARCHAR, 
	source_reference VARCHAR, 
	observed_date TIMESTAMP WITH TIME ZONE, 
	retrieved_date TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	confidence INTEGER, 
	source_result_id VARCHAR, 
	related_entity_id VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(source_id) REFERENCES research_sources (id), 
	FOREIGN KEY(source_result_id) REFERENCES source_results (id)
);
CREATE INDEX ix_evidence_id ON evidence (id);
