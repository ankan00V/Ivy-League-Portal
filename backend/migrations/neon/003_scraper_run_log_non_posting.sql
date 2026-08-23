-- Persist the non-posting reject count on scraper run logs.
--
-- scrape_and_store has always computed non_posting_count - rows fetched but
-- rejected before the scope check as not being an opportunity posting at all
-- (site navigation, marketing copy, category links). Nothing wrote it down.
--
-- The cost of that omission: a source returning pure navigation logged
-- items_parsed=0, items_out_of_scope=0, parse_error_count=0, which is byte for
-- byte what a healthy source that found nothing new logs. devpost, handshake
-- and wayup each ran 229 times at 0 inserts and looked like quiet days.
--
-- Backfills to 0 rather than NULL: historical rows genuinely did not record it,
-- and 0 is the value every consumer already assumes for a missing count.
ALTER TABLE app.scraper_run_logs
    ADD COLUMN IF NOT EXISTS items_non_posting bigint DEFAULT 0;
