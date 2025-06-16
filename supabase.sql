-- WARNING: This schema is for context only and is not meant to be run.
-- Table order and constraints may not be valid for execution.

CREATE TABLE public.annotations (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  highlight_id uuid,
  content text NOT NULL,
  annotation_type text DEFAULT 'note'::text,
  page_number integer,
  position jsonb,
  tags jsonb DEFAULT '[]'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT annotations_pkey PRIMARY KEY (id),
  CONSTRAINT annotations_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id),
  CONSTRAINT annotations_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id),
  CONSTRAINT annotations_highlight_id_fkey FOREIGN KEY (highlight_id) REFERENCES public.highlights(id)
);
CREATE TABLE public.document_chat_messages (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  role text NOT NULL,
  content text NOT NULL,
  context jsonb DEFAULT '{}'::jsonb,
  sources jsonb DEFAULT '[]'::jsonb,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT document_chat_messages_pkey PRIMARY KEY (id),
  CONSTRAINT document_chat_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id),
  CONSTRAINT document_chat_messages_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id)
);
CREATE TABLE public.document_views (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  session_id text,
  pages_viewed jsonb DEFAULT '[]'::jsonb,
  time_spent integer DEFAULT 0,
  last_page integer,
  zoom_level double precision DEFAULT 1.0,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT document_views_pkey PRIMARY KEY (id),
  CONSTRAINT document_views_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id),
  CONSTRAINT document_views_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.highlights (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  highlight_text text NOT NULL,
  page_number integer NOT NULL,
  position jsonb NOT NULL,
  color text DEFAULT 'yellow'::text,
  created_at timestamp without time zone DEFAULT now(),
  comment text,
  highlight_type text DEFAULT 'text'::text,
  metadata jsonb DEFAULT '{}'::jsonb,
  CONSTRAINT highlights_pkey PRIMARY KEY (id),
  CONSTRAINT highlights_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id),
  CONSTRAINT highlights_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id)
);
CREATE TABLE public.intelligent_search_sessions (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  research_question text NOT NULL,
  knowledge_base_id uuid,
  query_strategies jsonb NOT NULL DEFAULT '[]'::jsonb,
  candidate_papers jsonb NOT NULL DEFAULT '[]'::jsonb,
  ranked_papers jsonb NOT NULL DEFAULT '[]'::jsonb,
  research_insights jsonb NOT NULL DEFAULT '{}'::jsonb,
  total_candidates integer DEFAULT 0,
  max_papers integer DEFAULT 25,
  confidence_score double precision DEFAULT 0.0,
  processing_time double precision DEFAULT 0.0,
  llama_model text DEFAULT 'llama-4'::text,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT intelligent_search_sessions_pkey PRIMARY KEY (id),
  CONSTRAINT intelligent_search_sessions_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id)
);
CREATE TABLE public.knowledge_base_analysis (
  id uuid NOT NULL DEFAULT uuid_generate_v4(),
  knowledge_base_id uuid NOT NULL UNIQUE,
  connections jsonb DEFAULT '{}'::jsonb,
  insights jsonb DEFAULT '{}'::jsonb,
  analytics jsonb DEFAULT '{}'::jsonb,
  generated_by character varying,
  created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
  updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT knowledge_base_analysis_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_base_analysis_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id)
);
CREATE TABLE public.knowledge_base_insights (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  knowledge_base_id uuid NOT NULL,
  insights jsonb NOT NULL DEFAULT '[]'::jsonb,
  trends jsonb DEFAULT '[]'::jsonb,
  research_gaps jsonb DEFAULT '[]'::jsonb,
  key_connections jsonb DEFAULT '[]'::jsonb,
  generated_by text DEFAULT 'llama-4'::text,
  generated_at timestamp without time zone DEFAULT now(),
  expires_at timestamp without time zone DEFAULT (now() + '30 days'::interval),
  CONSTRAINT knowledge_base_insights_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_base_insights_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id)
);
CREATE TABLE public.knowledge_base_papers (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  knowledge_base_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  added_at timestamp without time zone DEFAULT now(),
  added_by uuid,
  CONSTRAINT knowledge_base_papers_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_base_papers_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id),
  CONSTRAINT knowledge_base_papers_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id),
  CONSTRAINT knowledge_base_papers_added_by_fkey FOREIGN KEY (added_by) REFERENCES public.profiles(id)
);
CREATE TABLE public.knowledge_base_shares (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  knowledge_base_id uuid NOT NULL,
  shared_with_user_id uuid,
  shared_by_user_id uuid NOT NULL,
  permissions text DEFAULT 'read'::text,
  public_link_id text UNIQUE,
  created_at timestamp without time zone DEFAULT now(),
  expires_at timestamp without time zone,
  CONSTRAINT knowledge_base_shares_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_base_shares_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id),
  CONSTRAINT knowledge_base_shares_shared_with_user_id_fkey FOREIGN KEY (shared_with_user_id) REFERENCES public.profiles(id),
  CONSTRAINT knowledge_base_shares_shared_by_user_id_fkey FOREIGN KEY (shared_by_user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.knowledge_bases (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  name text NOT NULL,
  description text,
  tags jsonb DEFAULT '[]'::jsonb,
  is_public boolean DEFAULT false,
  status text DEFAULT 'active'::text,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT knowledge_bases_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_bases_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.knowledge_canvases (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  knowledge_base_id uuid NOT NULL,
  user_id uuid NOT NULL,
  title text NOT NULL,
  paper_network jsonb NOT NULL DEFAULT '{}'::jsonb,
  research_themes jsonb NOT NULL DEFAULT '[]'::jsonb,
  methodology_evolution jsonb NOT NULL DEFAULT '{}'::jsonb,
  research_timeline jsonb NOT NULL DEFAULT '[]'::jsonb,
  cross_paper_insights jsonb NOT NULL DEFAULT '[]'::jsonb,
  research_gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
  future_opportunities jsonb NOT NULL DEFAULT '[]'::jsonb,
  collaboration_suggestions jsonb NOT NULL DEFAULT '[]'::jsonb,
  paper_count integer DEFAULT 0,
  analysis_depth text DEFAULT 'deep'::text,
  processing_time double precision DEFAULT 0.0,
  confidence_score double precision DEFAULT 0.0,
  llama_model text DEFAULT 'llama-4'::text,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT knowledge_canvases_pkey PRIMARY KEY (id),
  CONSTRAINT knowledge_canvases_knowledge_base_id_fkey FOREIGN KEY (knowledge_base_id) REFERENCES public.knowledge_bases(id)
);
CREATE TABLE public.paper_chunks (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id uuid NOT NULL,
  chunk_id text NOT NULL,
  content text NOT NULL,
  page_number integer,
  section text,
  chunk_index integer,
  bbox jsonb,
  embedding USER-DEFINED,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT paper_chunks_pkey PRIMARY KEY (id),
  CONSTRAINT paper_chunks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id),
  CONSTRAINT paper_chunks_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id)
);
CREATE TABLE public.paper_connection_analyses (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_ids ARRAY NOT NULL,
  analysis_types ARRAY NOT NULL DEFAULT ARRAY['methodology'::text, 'findings'::text, 'theoretical'::text],
  connections jsonb NOT NULL DEFAULT '[]'::jsonb,
  themes jsonb NOT NULL DEFAULT '[]'::jsonb,
  contradictions jsonb NOT NULL DEFAULT '[]'::jsonb,
  knowledge_gaps jsonb NOT NULL DEFAULT '[]'::jsonb,
  synthesis_opportunities jsonb NOT NULL DEFAULT '[]'::jsonb,
  collaboration_potential jsonb NOT NULL DEFAULT '[]'::jsonb,
  confidence_scores jsonb NOT NULL DEFAULT '{}'::jsonb,
  connection_depth text DEFAULT 'deep'::text,
  processing_time double precision DEFAULT 0.0,
  llama_model text DEFAULT 'llama-4'::text,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT paper_connection_analyses_pkey PRIMARY KEY (id)
);
CREATE TABLE public.paper_metrics (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  paper_id uuid NOT NULL UNIQUE,
  quality_score integer,
  relevance_score integer,
  venue text,
  h_index integer,
  downloads integer DEFAULT 0,
  saves integer DEFAULT 0,
  calculated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT paper_metrics_pkey PRIMARY KEY (id),
  CONSTRAINT paper_metrics_paper_id_fkey FOREIGN KEY (paper_id) REFERENCES public.papers(id)
);
CREATE TABLE public.papers (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  paper_id text NOT NULL,
  title text NOT NULL,
  abstract text,
  authors jsonb NOT NULL DEFAULT '[]'::jsonb,
  year integer,
  topics jsonb DEFAULT '[]'::jsonb,
  pdf_url text NOT NULL,
  pdf_file_path text,
  full_text text,
  citations integer DEFAULT 0,
  institution text,
  impact_score double precision DEFAULT 0.0,
  processing_status text DEFAULT 'pending'::text,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT papers_pkey PRIMARY KEY (id),
  CONSTRAINT papers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.profiles (
  id uuid NOT NULL,
  full_name text,
  avatar_url text,
  subscription_tier text DEFAULT 'free'::text,
  created_at timestamp without time zone DEFAULT now(),
  updated_at timestamp without time zone DEFAULT now(),
  CONSTRAINT profiles_pkey PRIMARY KEY (id),
  CONSTRAINT profiles_id_fkey FOREIGN KEY (id) REFERENCES auth.users(id)
);
CREATE TABLE public.research_insights (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  context_type text NOT NULL,
  context_id uuid NOT NULL,
  insight_types ARRAY NOT NULL DEFAULT ARRAY['trends'::text, 'gaps'::text, 'opportunities'::text],
  insights jsonb NOT NULL DEFAULT '[]'::jsonb,
  trending_topics jsonb NOT NULL DEFAULT '[]'::jsonb,
  emerging_methodologies jsonb NOT NULL DEFAULT '[]'::jsonb,
  research_opportunities jsonb NOT NULL DEFAULT '[]'::jsonb,
  collaboration_suggestions jsonb NOT NULL DEFAULT '[]'::jsonb,
  actionable_next_steps jsonb NOT NULL DEFAULT '[]'::jsonb,
  confidence_assessment jsonb NOT NULL DEFAULT '{}'::jsonb,
  supporting_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  time_horizon text DEFAULT 'mixed'::text,
  processing_time double precision DEFAULT 0.0,
  llama_model text DEFAULT 'llama-4'::text,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT research_insights_pkey PRIMARY KEY (id)
);
CREATE TABLE public.search_history (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  query text NOT NULL,
  search_type text DEFAULT 'papers'::text,
  filters jsonb DEFAULT '{}'::jsonb,
  results_count integer DEFAULT 0,
  clicked_results jsonb DEFAULT '[]'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT search_history_pkey PRIMARY KEY (id),
  CONSTRAINT search_history_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);
CREATE TABLE public.user_activity (
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL,
  activity_type text NOT NULL,
  entity_type text,
  entity_id uuid,
  metadata jsonb DEFAULT '{}'::jsonb,
  created_at timestamp without time zone DEFAULT now(),
  CONSTRAINT user_activity_pkey PRIMARY KEY (id),
  CONSTRAINT user_activity_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.profiles(id)
);