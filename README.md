# BactoWise

Assess bacterial genome quality and annotate genes — one command, one config file.

BactoWise runs **CheckM** (quality control) first, then **Prokka** and **Bakta** simultaneously once QC completes. If the genome fails the quality thresholds, BactoWise warns you and continues — the scientist makes the final call.

```
Stage 1:  CheckM          → completeness & contamination check
Stage 2:  Prokka + Bakta  → gene annotation (run in parallel)
```

---

## One-time setup

### 1. Install Docker

Docker runs Bakta inside a sealed container so you don't have to install it manually.

| OS | Steps |
|---|---|
| **Mac** | Download from [docker.com](https://docker.com) → drag to Applications → open it. You'll see a whale 🐳 in your menu bar when it's running. |
| **Windows** | Download installer from [docker.com](https://docker.com) → run it → start Docker Desktop from the Start menu. |
| **Linux** | `sudo apt install docker.io && sudo systemctl start docker` then `sudo usermod -aG docker $USER && newgrp docker` to grant your user permission. |

Verify it works:
```bash
docker run hello-world
# Should print: "Hello from Docker!"
```

---

### 2. Build and install BactoWise

From the root of the `bactowise` project directory:

```bash
# Build the conda package locally
conda build conda_recipe/ -c bioconda -c conda-forge

# Install from your local build
conda install --use-local bactowise -c bioconda -c conda-forge
```

> **WSL users:** If `conda build` fails with a bash syntax error near `(`, run:
> ```bash
> export PATH=$CONDA_PREFIX/bin:/usr/bin:/bin
> conda mambabuild --suppress-variables -c conda-forge -c bioconda conda_recipe/
> ```

---

### 3. Download the Bakta database (~2 GB, one-time)

```bash
bakta_db download --output ~/bakta_db --type light
```

Update `pipeline.yaml` if you save it somewhere other than `~/bakta_db`:
```yaml
database:
  path: "~/bakta_db"
```

---

### 4. Download the CheckM database (~2 GB, one-time)

```bash
mkdir -p ~/checkm_db
cd ~/checkm_db
wget https://data.ace.uq.edu.au/public/CheckM_databases/checkm_data_2015_01_16.tar.gz
tar -xzf checkm_data_2015_01_16.tar.gz
rm checkm_data_2015_01_16.tar.gz
```

Then point BactoWise to it in `pipeline.yaml`:
```yaml
- name: checkm
  database:
    path: "~/checkm_db"   # change this if you saved the database elsewhere
```

That's it. BactoWise automatically runs `checkm data setRoot` inside `checkm_env` every preflight — you never have to do it manually.

---

### 5. Download the test genome (optional but recommended)

```bash
# M. genitalium G37 — the "Hello World" of bacterial genomes (~580 kb, very fast to annotate)
efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta
```

Or download directly from NCBI:
`https://www.ncbi.nlm.nih.gov/nuccore/NC_000908.2?report=fasta`

---

## Running the pipeline

**Step 1 — Validate your config:**
```bash
bactowise validate -c pipeline.yaml
```

**Step 2 — Run:**
```bash
bactowise run -f mgenitalium.fasta -c pipeline.yaml
```

**Step 3 — Find your results:**
```
results/
├── checkm/
│   ├── checkm_summary.tsv   ← completeness & contamination metrics
│   ├── checkm_out/          ← full CheckM output
│   └── logs/
├── prokka/
│   ├── prokka_output.gff
│   ├── prokka_output.gbk
│   └── logs/
└── bakta/
    ├── *.gff3
    ├── *.gbff
    └── logs/
```

---

## Understanding the QC output

`checkm_summary.tsv` contains one row per genome with columns including:

| Column | Description |
|---|---|
| `Completeness` | % of expected marker genes found — higher is better |
| `Contamination` | % of marker genes found more than once — lower is better |
| `Strain heterogeneity` | % of contamination from closely related strains |

**Default pass criteria** (configurable in `pipeline.yaml`):
- Completeness > 95%
- Contamination < 5%

If the genome fails either threshold, BactoWise prints a warning before running annotation. You can adjust thresholds in `pipeline.yaml`:

```yaml
- name: checkm
  qc_criteria:
    completeness: 90.0   # relax if working with difficult genomes
    contamination: 10.0
```

---

## Customising the pipeline

The full default `pipeline.yaml` with all three tools:

```yaml
tools:
  - name: checkm
    version: "1.2.3"
    runtime: conda
    role: qc
    conda_env:
      name: "checkm_env"
      channels: [bioconda, conda-forge]
      dependencies: [python=3.8]
    qc_criteria:
      completeness: 95.0
      contamination: 5.0
    params:
      mode: taxonomy_wf   # taxonomy_wf (~2GB db) or lineage_wf (~40GB db, more accurate)
      rank: domain
      taxon: Bacteria
      threads: 4

  - name: prokka
    version: "1.14.6"
    runtime: conda
    depends_on: [checkm]
    conda_env:
      name: "prokka_env"
      channels: [bioconda, conda-forge]
      dependencies: [python=3.8]
    params:
      genus: "Mycoplasma"
      species: "genitalium"
      kingdom: Bacteria
      cpus: 4

  - name: bakta
    version: "1.12.0"
    runtime: docker
    depends_on: [checkm]
    image: "oschwengers/bakta:v1.12.0"
    database:
      path: "~/bakta_db"
      type: light
    params:
      min-contig-length: 200
      threads: 4

output_dir: "./results"
threads: 4
```

### Switching CheckM to lineage_wf (more accurate, ~40 GB database)

```yaml
params:
  mode: lineage_wf
  threads: 4
```

The `lineage_wf` database is ~40 GB. Download it the same way as above and point `database.path` in `pipeline.yaml` to the same directory — BactoWise will call `checkm data setRoot` automatically.

### Skipping QC and running annotation only

Remove the `checkm` block and the `depends_on` lines from prokka and bakta.
Prokka and Bakta will then run in parallel from the start with no QC gate.

### Adding a future tool (e.g. PGAP)

```yaml
  - name: pgap
    version: "2024-07-18.build7555"
    runtime: docker
    depends_on: [checkm]
    image: "ncbi/pgap:2024-07-18.build7555"
    database:
      path: "~/pgap_db"
```

---

## Troubleshooting

| Error | Fix |
|---|---|
| `Cannot connect to Docker` | Open Docker Desktop, wait for the whale 🐳 to stop animating |
| `Database not found at ~/bakta_db` | Run `bakta_db download --output ~/bakta_db --type light` |
| `CheckM database path not found` | Download the database and set `database.path` in `pipeline.yaml` — see setup step 4 |
| `checkm_env not found` | Run `conda create -n checkm_env -c bioconda -c conda-forge checkm-genome=1.2.3 python=3.8 -y` |
| `prokka not found on PATH` | BactoWise creates `prokka_env` automatically on first run — check preflight output |
| `bactowise: command not found` | Run `conda activate <your-env>` first |
| CheckM fails silently | Check `results/checkm/logs/checkm.log` for the full error |
