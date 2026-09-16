> **Note:** This file was generated against an earlier version of the gym-anything
> library. Some paths (e.g. `gym_anything/runners/...`, `examples/<env>/...`,
> `constants.py`) and APIs (e.g. `env.verify()`, `env._runner.ssh_port`) referenced
> below may have moved or been renamed. Cross-check against the current source tree
> (`src/gym_anything/...`, `benchmarks/cua_world/environments/...`,
> `env.get_session_info()`) before relying on any path or import here.

# Visallo Environment Notes

## Key Learnings

### Version Selection
- Visallo 3.1.4 has a dependency on a custom/patched Vertexium build with `org.vertexium.security.VisibilityParseException` that doesn't exist in standard Maven Central artifacts. **Use Visallo 2.2.14 instead.**
- Visallo 4.0.0 has no pre-built WAR on Maven Central.
- The original Visallo GitHub repo (github.com/visallo/visallo) returns 404; use forks (FantasyNitroGEN/visallo, DanielCYLim/visallo).

### Architecture (No Docker Needed)
- Visallo can run without Accumulo/Hadoop/ZooKeeper/RabbitMQ by using:
  - `graph=org.vertexium.inmemory.InMemoryGraph` (in-memory graph store)
  - External Elasticsearch for search
  - `repository.workQueue=org.visallo.model.queue.inmemory.InMemoryWorkQueueRepository`
  - `simpleOrmSession=com.v5analytics.simpleorm.InMemorySimpleOrmSession`
- Only needs: Java 8 + Elasticsearch 1.7.6 + Jetty 9.4

### Critical Dependencies Not in the WAR
The WAR file does NOT include these JARs that must be added separately:
- `vertexium-inmemory-2.4.7.jar` + `vertexium-core-2.4.7.jar` (graph engine)
- `vertexium-elasticsearch-singledocument-2.4.7.jar` (search index)
- `visallo-model-vertexium-2.2.14.jar` + `visallo-model-vertexium-inmemory-2.2.14.jar`
- `visallo-model-queue-inmemory-2.2.14.jar`
- `visallo-web-auth-username-only-2.2.14.jar`
- `simple-orm-in-memory-1.3.0.jar` + `simple-orm-core-1.3.0.jar`
- `elasticsearch-1.4.4.jar` (ES client)
- All Lucene 4.10.3 JARs (12+ modules)
- `recurrent-0.3.3.jar` (retry library, NOT 0.5.0 which has API changes)
- `groovy-2.4.5.jar`, `spatial4j-0.4.1.jar`

### Elasticsearch Configuration
- Config property is `graph.search.locations=localhost` (NOT `esLocations`)
- Vertexium internally strips `graph.search.` prefix and looks for `locations`
- Port `9300` (transport protocol), not `9200` (HTTP REST)
- Cluster name MUST match: `graph.search.clusterName=visallo` = ES `cluster.name: visallo`
- Must install Vertexium ES plugin: `vertexium-elasticsearch-singledocument-plugin-2.4.7.jar` into ES plugins/vertexium/

### Ontology Setup
- Sample ontology OWL file from GitHub: `FantasyNitroGEN/visallo/master/config/ontology-sample/sample.owl`
- Requires icon PNG files for each concept class (e.g., `person.png`, `location.png`)
- Icon names are **camelCase** (contactInformation.png, not contact_information.png)
- Extract `entity.png` from `visallo-core-*.jar` as the base icon for all concept types

### Lucene Version
- ES 1.4.4 needs Lucene 4.10.3 (NOT 4.10.2 or 4.10.4)
- `NoSuchFieldError: LUCENE_4_10_3` means wrong Lucene version

### Login Coordinates (1920x1080)
- Username field: approximately (960, 560) on maximized Firefox
- Login button: Enter key works after typing username

### Ontology Intent Bug (CRITICAL)
- Custom OWL files will cause: `VisalloException: Could not find concept by intent: entityImage`
- The official `sample.owl` declares `<visallo:intent>entityImage</visallo:intent>` on the `image` class
- Without this, the Visallo Router fails to initialize and returns HTTP 503
- **MUST use the official sample.owl** from `FantasyNitroGEN/visallo/master/config/ontology-sample/sample.owl`

### Snap Firefox (Ubuntu 22.04+)
- Firefox is snap-installed on the base Ubuntu GNOME image
- The `--profile` flag does NOT work with snap Firefox
- Profile directory: `~/snap/firefox/common/.mozilla/firefox/default-release/`
- Must do a warm-up launch first to create the snap profile directory structure
- Then inject `user.js` into the snap profile directory
- Lock files exist in BOTH `~/.mozilla/` and `~/snap/firefox/` directories - must clean both
- Use `find ... | xargs rm -f` pattern to clean all lock files everywhere
- Launch Firefox WITHOUT `--profile` flag: `setsid firefox http://localhost:8080/`

### Environment Timing (verified 2026-04-02)
- pre_start (installation): ~50-70s (with cached base QCOW2)
- post_start (ES + Jetty + Firefox): ~45-50s
- pre_task (Firefox restart + login): ~13s
- Total: ~107s with cached base image
- First run without cache: ~535s (downloads ES, Jetty, WAR, plugins)
