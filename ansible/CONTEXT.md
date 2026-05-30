# Cicalak

Cicalak is the user's personal home network infrastructure. It encompasses a physical Home Network on the LAN and a set of publicly reachable Public Gateways, all united under a single ownership identity and naming scheme.

This glossary was developed during a grill-with-docs session in May 2026. It reflects the actual operating philosophy and mental model of the Solo Operator rather than an idealized architecture.

## Language

**Cicalak**:
The logical and ownership umbrella for the user's entire personal infrastructure. The name originates from Hungarian "home of cats"; the owner affectionately refers to their children as "cica" (kitten). All WiFi networks in the home carry "cica" in their SSID. Cicalak also functions as the namespace for domains owned by the user (cicalak.de, cicalak.online, and related names) under which hosts and services are addressed.

Cicalak contains two distinct network segments that are managed together but have very different connectivity characteristics:
- the private Home Network
- the publicly accessible Public Gateways

The working categories used to classify participants are intentionally pragmatic and have been retained because they continue to serve operational needs effectively, even when they are influenced by implementation concerns.

_Avoid_: homelab, home lab, personal cloud, the network, my setup

**Cica**:
An affectionate Hungarian term for "kitten" used by the owner as a nickname for their children. It is the root of the name Cicalak and appears in all home WiFi network names.

_Avoid_: cat, kitten (when referring to the naming theme)

**Musician Memorial Naming**:
The practice of naming Cicalak hosts after recently deceased notable musicians as a mark of respect. The specific choice of artist carries no operational or semantic meaning; it is a personal gesture only.

_Avoid_: rockstar naming, artist naming, whimsical naming, memorial naming (when not specific to musicians)

**Home Network**:
The physical, mostly non-publicly-routable LAN segment of Cicalak containing the owner's actual on-premises devices and sensitive personal data (for example files on shared storage). The Home Network follows a deliberate security model in which outsiders must never see it directly; all access is mediated through Public Gateways. Once legitimately inside the Home Network, there is intentionally little additional protection or segmentation between participants.

_Avoid_: LAN, internal network, home lab network

**External Invisibility**:
The foundational security principle of the Home Network: it is kept deliberately invisible and unreachable from the public internet. Direct inbound access is considered not worth the ongoing effort and risk; the strong boundary is "outsiders should not see the Home Network at all."

_Avoid_: security by obscurity, hide and hope, perimeter security (generic)

**Trusted Interior**:
The operating assumption inside the Home Network: once traffic has entered through legitimate means (via a Public Gateway), participants largely trust each other with minimal further authentication, segmentation, or hardening. "Cicalak is not really protected as soon as you are inside."

_Avoid_: zero trust, defense in depth, flat network (without the specific trusted-interior meaning)

**Public Gateway**:
A publicly reachable member of Cicalak whose primary purpose is to act as the public face and entry point for the Home Network. Public Gateways are logically part of Cicalak (same ownership, naming, and management) but sit outside the Home Network from a network topology perspective. They enable inbound access and proxying to services that actually live in the Home Network.

_Avoid_: jump server, bastion, cloud VPS, cloud host (when speaking in domain terms)

**Central File Storage**:
The primary shared storage for important personal and family data inside the Home Network. It is hosted on one dedicated storage participant and accessed by other machines as needed. Performance-sensitive services (for example large media libraries) may keep their active working data on their own local disks instead of the central store when network latency or throughput would be a bottleneck.

_Avoid_: NAS, file server, shared storage (generic)

**Home Service with Public Proxy**:
The standard, preferred pattern for services that must be reachable from the internet. The actual service and its data run inside the Home Network (using Central File Storage or local disks as appropriate). Only a proxy or ingress is exposed publicly through a Public Gateway. This approach is chosen because it is easy, safe, and inexpensive.

_Avoid_: reverse proxy, edge service, cloud-native service

**Data Placement**:
Different categories of data are intentionally located in different places according to sensitivity, access patterns, and convenience:
- Important personal and family data lives in Central File Storage inside the Home Network (protected by External Invisibility).
- Practical daily data for mobile and everyday use is kept in commercial cloud storage (for example OneDrive).
- Long-term / cold backups are stored in offsite object storage (Backblaze, S3 Deep Archive).
- Future peer-to-peer storage sharing with trusted external parties is under consideration.

_Avoid_: data strategy, storage tiers (generic)

**Solo Operator**:
Cicalak is managed and administered by a single person. Other humans (family members, etc.) are consumers who use services and data but do not participate in management, configuration, or operations.

_Avoid_: single admin, one-person operation (without the specific meaning)

**Bootstrap Gate**:
A narrow, deliberate manual process required for every new device (especially Pis) before Ansible can take over. Its only purpose is to establish passwordless SSH reachability for the ansible user and passwordless sudo. After this gate the device is handed over to full Ansible management. The only major operations still performed manually are OS major version upgrades (Ubuntu, Raspberry Pi OS, etc.). The operator uses a checklist to perform the gate reliably.

_Avoid_: initial provisioning, first boot, device setup (generic)

**Unified Management**:
A core operating principle of Cicalak: any new hardware (physical machines or cloud instances) is brought under the single existing management system as quickly as possible. The goal is that it receives regular updates and configuration together with the rest of the fleet rather than being maintained in isolation.

_Avoid_: homogeneous fleet, standardized hardware

**Personal Experimentation Platform**:
In addition to hosting useful services, Cicalak serves as a personal laboratory for gaining hands-on experience with technologies. Examples include running k3s clusters (used as interview demonstration material) and experimenting with GPU-based local AI workloads (Ollama and future home AI projects). Older hardware with usable GPUs is deliberately retained for this purpose.

_Avoid_: homelab for fun, learning environment (generic)

**Control Tower**:
The designated machine (currently an old laptop with a broken display) that serves as the single convenient origin point from which the Solo Operator executes Ansible to manage the entire fleet. It is chosen because it can reach all other participants. No permanent services run on it. It is explicitly recognized as a single point of failure for management and orchestration operations, with plans to add additional control nodes as future mitigation.

_Avoid_: bastion host, jump server, management server (without the specific "orchestration origin" meaning)

**Emergent Structure**:
Cicalak does not maintain a formal separation between stable services and experimental, historical, or temporary components. It is accepted as a colorful, pragmatic mix of things that has grown organically and "happens to work." There is awareness that more deliberate structure (for example clearer boundaries or systematic cleanup of legacy experiments) may be introduced gradually in the future.

_Avoid_: chaos, technical debt (when used pejoratively)

## Example Dialogue

Operator: "The new Banana Pi won't join the WiFi."
Expert: "Did you use the cica SSID and the right password from the setup notes?"
Operator: "Yes, but it's still not getting an address on the Home Network."
Expert: "Then it needs to be properly introduced and granted access before it can become a full participant in the Cicalak Home Network."

---

## Findings from May 2026 Grill Session

This section captures the key insights from the structured exploration of the ansible repository and the operator's explanations. It is intended as a practical reference for future work (refactoring, automation, documentation, or breaking improvements into tasks).

### Core Operating Philosophy
- Cicalak is run by a **Solo Operator** who manages everything himself. Family and others are consumers only.
- The system is deliberately pragmatic and emergent ("a colorful mix that happens to work") rather than following strict engineering patterns such as test/prod separation or clean historical cleanup.
- Two strong drivers for the heterogeneous fleet:
  - **Unified Management**: Bring any new hardware under the same system quickly so it gets regular updates without separate maintenance burden.
  - **Personal Experimentation Platform**: The fleet is also a personal lab for learning (k3s experience used in interviews, GPU/AI experiments with Ollama and future home AI work).

### Key Architectural Patterns
- Strong preference for **External Invisibility** of the Home Network + controlled entry only through **Public Gateways**.
- **Home Service with Public Proxy** is the standard safe/cheap pattern for externally reachable services.
- Data is placed pragmatically across **Central File Storage** (important/family data), commercial cloud for daily convenience, and offsite backups.
- New devices pass through a narrow **Bootstrap Gate** (SSH + sudo setup via checklist). After that, everything is Ansible-managed except major OS upgrades.
- The **Control Tower** (currently an old laptop) is the single convenient origin for running Ansible against the whole fleet. It is a known single point of failure for management; additional control nodes are planned.

### Current State of the Ansible Codebase
- The inventory groups and roles are intentionally pragmatic operational categories that have served the operator well.
- `site.yml` is the main orchestration point, run manually from the Control Tower when upgrades or new functionality are needed.
- Significant historical/experimental code remains (commented k3s, WireGuard, old deployments). CUDA playbook is actively maintained and used for NVIDIA driver + Docker GPU runtime setup (enables Immich ML CUDA accel on KoborJanos per #59; not auto-invoked in site.yml). These are kept as reference or because cleanup has not been prioritized.
- Safety mechanisms exist for updates and reboots, but the overall process remains manual and opportunistic.

### Recommended Directions for Future Work
- The operator has expressed interest in gradual improvement, including potential automation (e.g. Airflow) and additional control nodes.
- Any future refactoring or new automation should respect the Emergent Structure and Solo Operator realities rather than imposing heavy enterprise patterns.
- The current CONTEXT.md glossary is the primary reference for shared language when discussing changes.

**Desired Collaboration & Delivery Process (Initial Version)**

The operator's preferred way of working, at least in the beginning, is:

1. Formulate issues.
2. Grill them (using structured domain exploration such as grill-with-docs).
3. Implement the changes, preferably using the afk skill for autonomous execution.
4. Human review of the resulting changes.
5. On the Control Tower (prince), the operator does `git pull` followed by `ansible-playbook site.yml` to bring the change into the live fleet.

This flow is intentionally pragmatic: start delivering value and iterating immediately rather than designing a perfect process or infrastructure up front and doing a big-bang rollout later. The process itself can (and will) be improved over time while already being used.

This session produced no Architecture Decision Records. The understanding captured here can be used as input for future planning, task breakdown, or further documentation.

## Ingress Redundancy (Reverse SSH Tunnels) — Added 2026-05 (issue #50)

As of the P0 work for GitHub czaby/grok#50, Cicalak has two independent reverse SSH tunnel ingress paths for the Solo Operator when traveling:

- **Primary / legacy (untouched)**: `cherry` (Public Gateway) ← autossh reverse from `MatePeter` (home landing). Port 2222. Playbook: `playbooks/autossh_reverse_tunnel.yml` (and the shared `reverse-ssh-tunnel.service.j2` template). **This path and its playbook must remain 100% untouched** per the explicit non-negotiable constraint from the grill session.

- **Redundant / new (2026-05 delivery)**: `jerryleelewis` (Oracle Public Gateway, also serving `immich.cicalak.de` and WireGuard) ← autossh reverse from `FlorianSchneiderAsus` (daily-driver laptop, usually powered on, home landing). Port **2224**. 
  - Dedicated narrow playbook: `playbooks/autossh_reverse_tunnel_jerry_florian.yml` (home/client side only).
  - Reuses the existing systemd unit template and the `setup_online.yml` + `public_keys/` mechanism for auth key distribution.
  - Cloud-side (jerryleelewis) preparation ( `GatewayPorts clientspecified` in sshd_config + opening 2224/tcp in the firewall) is performed via a documented one-time manual checklist embedded in the playbook header. This manual gate protects the higher-priority production Immich proxy on the same host. Long-term target: capture as IaC in a future play targeting the `oracle` group.

**Why these machines**: jerryleelewis is already a live Public Gateway (WireGuard server, Immich ingress). FlorianSchneiderAsus is a reliable always-on-ish participant inside the Home Network.

**Security model**: Same as the legacy tunnel — high port + key-only auth + `-R *:` bind. External Invisibility of the Home Network remains the primary posture; these tunnels are narrow, known-only-to-operator backdoors for the Solo Operator.

**Verification from external network** (mobile hotspot etc.):
- `ssh -p 2224 ubuntu@jerryleelewis.cicalak.de` → lands on FlorianSchneiderAsus.
- From there: reach other home participants by name (Trusted Interior) and run Ansible commands.

**Run / update**: `ansible-playbook site.yml` (or the two specific playbooks). The new import was added to `site.yml` after `setup_online.yml`.

**Pubkey bootstrap for the new tunnel**: The ansible user's SSH public key from FlorianSchneiderAsus must be placed in `playbooks/public_keys/ansible_florianschneiderasus.pub` (replacing the placeholder comments) before the first run. See the detailed extraction + replacement instructions inside the new playbook and the placeholder file itself.

**Documentation location for the full operator checklist + runbook**: The header of `playbooks/autossh_reverse_tunnel_jerry_florian.yml` (extensive comments covering manual jerry prep, key step, acceptance criteria, and future evolution).

This addition directly addresses the "only one reliable travel ingress" pain point from the parent epic (#54) while strictly respecting all constraints from the grill session and Cicalak philosophy (Emergent Structure, Solo Operator, Unified Management, no big-bang changes).

Future related work: #51 (WireGuard as primary robust path), making the jerry cloud prep fully Ansible-driven, and adding a secondary Control Tower node.

## Immich Photo Service — Concrete State (June 2026)

**Primary Immich Instance**: KoborJanos (a participant in the Home Network that also has a GPU, required for the `immich-machine-learning` container).

Data placement on the Primary Immich Instance (all local to KoborJanos unless noted):
- Media / originals / thumbs: `/mnt/WD1T/czaby/immich` (on the dedicated 1 TB Western Digital internal drive WD1T).
- Postgres database (with Immich vector extensions): `/home/czaby/postgres` (on the root disk of KoborJanos).
- Daily operational backup target for the deployment config: `/mnt/me/immich_backup` (NFS mount from Central File Storage on quincyjones).

**Immich Public Ingress** (Home Service with Public Proxy pattern):
- Traefik runs on jerryleelewis (the Oracle Public Gateway, also serving WireGuard).
- The docker-compose on KoborJanos attaches the `immich-server` to an external `traefik` network and uses Traefik labels for `Host(`immich.cicalak.de`)`, websecure entrypoint, and the `myresolver` certresolver.
- A narrow reverse autossh tunnel (started at boot via `/home/czaby/start-autossh.sh`) does `-R 127.0.0.1:2283:localhost:2283 jerryleelewis.cicalak.de`. It only forwards the app port to localhost on the Public Gateway (not a full `*` bind).

**Current Backup Mechanism** (as captured in the scripts added to the repo):
- Crontab on KoborJanos:
  - `@reboot`: `/home/czaby/start-autossh.sh` (waits for jerry reachability, then starts the narrow tunnel).
  - `@daily`: `/home/czaby/doDailyBackup.sh` which does `rsync -a` of the entire `/home/czaby/immich` directory (docker-compose.yml, .env, supporting files) to `/mnt/me/immich_backup/` on Central File Storage.
- `/home/czaby/immich` on KoborJanos is a symlink to the real media location on the WD1T drive (`/mnt/WD1T/czaby/immich`). Therefore the daily `rsync -a .` of the compose directory **does** walk and back up the entire photo/video library to `/mnt/me/immich_backup/` on Central File Storage (quincyjones). This is the current secondary copy inside the Home Network. (The backup script depends on this symlink; any future change to the symlink or the rsync target is a configuration change that must be reviewed under the "make backups better documented and more explicit" goal.)
- Postgres data remains only on the root disk of KoborJanos (no dumps visible in the scripts).
- No offsite / cold backup (outside Cicalak) exists yet for either the media library or the DB. The Solo Operator explicitly wants to reach a 1-2-3 backup posture for Immich (3 copies of data, on 2 different kinds of media, with at least 1 copy offsite / outside the Home Network + Central File Storage).

**History and "old useless backups"**:
Immich originally ran directly on jerryleelewis (the Public Gateway). Disk usage grew rapidly, so the service (and its data) was migrated to KoborJanos inside the Home Network. As a result there exist old Immich-era backup artifacts (B2 objects, directories, snapshots, or other copies) from the jerryleelewis period that are now considered "old useless backups" and should be discovered and deleted.

The Solo Operator requested that discovery of all such old Immich backups be done via a **separate, narrow GitHub issue** whose first deliverable is a small ansible playbook that can execute discovery commands across all Cicalak hosts. This separate ticket is intended to produce a clear, actionable list of cruft that can be safely removed before (or in parallel with) the larger resilience work. The main Immich resilience issue will be able to depend on it.

**Backup Verifiability and Disaster Recovery (added during grill)**:
The daily backups (the rsync to Central File Storage) were set up and manually tested at some point in the past. There is currently no ongoing automated or regular verification that a restore would actually succeed. The Solo Operator considers it unacceptable to discover during a real incident that the backups are broken or incomplete.

Additional requirements for the "make backups better documented and more explicit" goal:
- There must be a practical way to **verify that the backup is usable** (i.e., a test restore or equivalent that proves Immich can be brought back from the secondary copy on Central File Storage).
- There must be a **disaster recovery document** containing the exact commands and sequence needed to restore the Primary Immich Instance (media + postgres + docker-compose + network/tunnel configuration) from the backup.

These two artifacts (verification mechanism + DR runbook) are considered part of the backup hygiene work.

**Ticket packaging decision (resolved during grill)**:
The Solo Operator delegated the A/B packaging detail. Decision: the old-backup discovery, cruft cleanup, backup verifiability mechanism, and disaster recovery document with restore commands will all live together in **one narrow companion GitHub issue** (separate from the main Immich resilience issue). This single hygiene ticket will be the first vertical slice exercising ansible across Cicalak hosts for Immich concerns and will deliver both the discovery playbook and the trustworthiness artifacts. The main resilience issue will depend on it (or run in parallel after the hygiene baseline is improved).

**Data Placement Strategy for Failover (resolved during grill, Question 5)**:
The Solo Operator accepted the recommended direction:
- Primary Immich Instance (KoborJanos) keeps its current local disks for as long as they "fit comfortably" (WD1T for media via the symlink, root disk for postgres).
- For the Secondary Immich Instance: media will be made available via Central File Storage (NFS from quincyjones or a reliable copy into a secondary location on the same Central File Storage). Postgres will use periodic dumps + documented restore on failover.
- This keeps the secondary simple (performance is explicitly secondary), uses existing hardware, and makes proxy failover on jerryleelewis easier to implement.
- The daily rsync on Central File Storage + future offsite copy (1-2-3) remain the recovery sources.

**Secondary Immich Instance Constraints (resolved during grill, Question 6)**:
- The secondary must also run 24/7 (not a cold or warm standby that is only powered on or started during an incident).
- Cherry (the existing cherryservers Public Gateway) is explicitly ruled out — it is too small to host the secondary Immich instance.
- Concrete choice of which existing host will become the Secondary Immich Instance is deliberately deferred until after the narrow hygiene/discovery ticket has produced a full capability catalog of all Cicalak participants (disk capacity on relevant volumes, RAM, always-on characteristics, docker, reachability from jerryleelewis, etc.). Only then will the best existing 24/7 machine be selected before considering any new hardware.

The hygiene ticket is therefore the critical path enabler for the second server decision.

**Catalog Requirements (expanded during grill)**:
The narrow hygiene/discovery playbook must collect at minimum:
- Disks + free space on paths relevant to Immich media or restores
- RAM
- CPU / GPU presence and characteristics
- Power / always-on profile
- Docker availability and basic functionality
- Network reachability (especially to jerryleelewis and to Central File Storage)
- Any other factors that affect suitability for running the full Immich stack (including machine-learning)

**Explicit Host Exclusions for Secondary Immich Instance (stated during grill)**:
- **prince**: Must remain a clean Control Tower / ansible origin. No additional services or roles should be added to this old laptop.
- **MatePeter**: Old CPU. While Ubuntu still functions, some docker images (relevant to a full Immich stack) will not run reliably.
- **quincyjones** (current Central File Storage / NFS server): Must stay dedicated to its storage role. No Immich or other application workloads should be placed on it.

These exclusions, combined with the 24/7 requirement for the secondary, significantly narrow the pool of plausible existing hosts. The hygiene ticket is expected to surface the remaining viable candidates.

**Decision on Secondary Host Selection (resolved during grill)**:
The Solo Operator explicitly chose to defer all discussion and selection of the specific machine for the Secondary Immich Instance until after the narrow hygiene/discovery ticket has run and produced the capability catalog. No speculation on remaining candidates will be done in advance. The catalog (including CPU/GPU/power data and the stated exclusions) will be the sole input for that later decision.

**Immich Public Ingress Failover Behavior (resolved during grill, Question 9)**:
The failover must be fully automatic and health-check driven by Traefik on jerryleelewis. No manual steps are acceptable for the operator during an incident. A short downtime window (a few minutes) while health checks detect the primary failure and traffic is routed to the secondary is acceptable. The design should reuse the existing Traefik instance, certresolver, and label-driven routing. Each backend (primary and future secondary) will be reached via its own narrow reverse tunnel binding a distinct localhost port on jerryleelewis. Traefik will be configured with a load-balancer service containing both servers and health checks (primarily on the primary). When the primary fails its checks, Traefik automatically stops sending traffic to it.

**Upgrade Policy (resolved during grill)**:
Every time `ansible-playbook site.yml` is run against the relevant Immich hosts, the containers should be brought to the latest desired images (no separate manual upgrade step required). The operator does not want to remember or run a dedicated upgrade playbook. Exact ansible implementation details are delegated to the implementer.

**Media Storage for Primary + Secondary — Common Storage Decision (resolved during grill)**:
The Solo Operator chose common live storage (Option A) so that both the Primary and Secondary Immich Instances see the exact same media tree at all times. This eliminates the need for any media synchronization job between the two instances and makes both failover and backups significantly simpler.

Chosen live path: `/mnt/temp/immich` (mounted from Central File Storage on quincyjones via the existing `/mnt/temp` NFS export).

Consequences:
- The live `UPLOAD_LOCATION` for Immich (on both KoborJanos and the future secondary) will be the NFS path.
- The local WD1T drive on KoborJanos will no longer be the primary media store for Immich.
- The existing daily rsync on KoborJanos (`doDailyBackup.sh`) will no longer need to copy the media library (media is now under the Central File Storage backup domain).
- Backups of Immich media become "backup the relevant parts of the NFS export on quincyjones" (plus the offsite 1-2-3 leg).
- Postgres remains on the local root disk of each Immich instance (with periodic dumps for failover recovery). No common storage is planned for the database at this stage.
- The one-time migration of the existing ~1 TB library from the local WD1T path (`/mnt/WD1T/czaby/immich`) to the new common location `/mnt/temp/immich`, plus updating the live `UPLOAD_LOCATION` and the daily backup script on KoborJanos, is a distinct body of work. It may be included as a major deliverable inside the narrow hygiene ticket or packaged as its own small follow-on ticket, depending on size and risk.

This concrete picture was established during the grill-with-docs session for the new Immich resilience issue. It replaced earlier hypotheses that the service ran on quincyjones (the current Central File Storage host). The deployment was previously outside git and outside the ansible fleet (classic Emergent Structure).

**Avoid (for this service)**: treating the root-disk postgres as "Central File Storage" (it is local instance storage per Immich instance, recovered via dumps). The WD1T drive on KoborJanos is no longer the live media store after the migration to common storage on Central File Storage. Central File Storage (`/mnt/temp/immich`) is now the single live media location for both primary and secondary.

## Immich Photo Service — Post #57 Migration State (completed 2026)

The one-time ~1 TB live media migration from local WD1T (`/mnt/WD1T/czaby/immich`) to common Central File Storage path `/mnt/temp/immich` (NFS export from quincyjones) has been completed per GitHub issue #57.

**Updated Data Placement (Primary on KoborJanos)**:
- Media / originals / thumbs / library / upload artifacts: `/mnt/temp/immich` (Central File Storage, single source of truth for Primary + future Secondary Instance; no more local WD1T primary copy).
- Compose / config / .env / docker-compose.yml / hwaccel*.yml / scripts: `/home/czaby/immich` (now a regular small local directory on KoborJanos root/home disk; **no longer a symlink** into the media tree).
- Postgres: unchanged (`/home/czaby/postgres` on local root disk).
- Daily config backup target: still `/mnt/me/immich_backup` (tiny now; media no longer walked).

**Backup Implications (updated)**:
- The `doDailyBackup.sh` (deployed/updated via `playbooks/prepare_immich_central_storage.yml` template) now performs config-only rsync (explicit excludes for media dirs). It no longer contributes the secondary copy of the photo library.
- Media protection is now via whatever strategy protects the Central File Storage export on quincyjones (daily/DR + future offsite 1-2-3 leg per the resilience goals).
- The old WD1T tree on KoborJanos is eligible for cleanup after successful verification + at least one full backup cycle (documented in #57 handoff + playbook header).

**Symlink Resolution**:
- Pre-#57: `/home/czaby/immich` → `/mnt/WD1T/czaby/immich` (caused backup script to archive entire library).
- Post-#57: `/home/czaby/immich` is a plain dir (config only). The UPLOAD_LOCATION in the live .env on KoborJanos now points at the NFS path.

**Migration Artifacts (for operators + future automation)**:
- Prep + script deployment: `ansible/playbooks/prepare_immich_central_storage.yml` (narrow; run with `--limit KoborJanos`; rich header contains the exact numbered procedure, rollback recipe, timings, verification commands, and smoke tests).
- NFS path ensure (idempotent, also for Secondary prep): added to `roles/nfs/tasks/main.yml` (executed via normal `site.yml` or `nfs.yml` runs).
- Updated backup script template: `ansible/templates/doDailyBackup_immich.j2`.
- All changes were made in the isolated AFK worktree for #57 and are part of the ansible collection snapshot.

**Verification performed (recorded in #57 handoff comment)**: file count + spot checksums + du sizes + successful `docker compose up` against new tree + smoke tests (new upload, existing view, ML job with CUDA, UI health). NFS latency for ML was measured and noted.

The `/mnt/temp/immich` tree was created with 1000:1000 / 0755 (ready for Secondary per grill).

This completes the storage move vertical slice and unblocks clean #58 (resilience / secondary).

## Related Future Work (Parked)
- Later security/credential hygiene review across all cicalak-related repositories (explicitly requested to be done after the resilience improvements, not during this grill).
- **Extra small issue (explicitly requested during grill)**: Enable GPU acceleration for the `immich-machine-learning` container on KoborJanos (the host has a GPU, but the compose currently uses the plain CPU image with the hardware acceleration sections commented out). This is independent of the main resilience work and can be a quick win.
