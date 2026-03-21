# BactoWise — Documentation

- [User Guide](#user-guide)
  - [1. Installation](#1-installation)
  - [2. Databases](#2-databases)
  - [3. Running the pipeline](#3-running-the-pipeline)
  - [4. Skipping stages](#4-skipping-stages)
  - [5. Bypassing annotation with pre-computed GFF files](#5-bypassing-annotation-with-pre-computed-gff-files)
  - [6. Understanding QC output](#6-understanding-qc-output)
  - [7. Stage 3 — BactoWise Consensus Engine](#7-stage-3--bactowise-consensus-engine)
  - [8. Stage 4 — Supplementary Annotations](#8-stage-4--supplementary-annotations)
  - [9. Downstream analysis — pangenome with Panaroo](#9-downstream-analysis--pangenome-with-panaroo)
  - [10. Troubleshooting](#10-troubleshooting)
- [Developer Guide](#developer-guide)
  - [1. pipeline.yaml field reference](#1-pipelineyaml-field-reference)
  - [2. Modifying pipeline.yaml locally](#2-modifying-pipelineyaml-locally)
  - [3. Adding a new tool](#3-adding-a-new-tool)

---

# User Guide

## 1. Installation

### Singularity / Apptainer

Bakta and PGAP run inside Singularity containers. Singularity and Apptainer are
the same runtime — Apptainer is the actively maintained community fork and is
recommended for new installs. The two are fully interchangeable; BactoWise
detects whichever is available on your PATH.

**On an HPC cluster (most common case):**
```bash
module load singularity
# or: module load apptainer
```

**On a local workstation (WSL2, Linux):**
```bash
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
```

Verify it works:
```bash
apptainer exec docker://alpine cat /etc/alpine-release
# Should print an Alpine Linux version number
```

If this step fails with a namespace or kernel error, install the setuid
variant instead:
```bash
sudo apt install -y apptainer-suid
```
This is standard on HPC clusters with older kernels and is perfectly safe.

### BactoWise

From the root of the project directory:

```bash
conda build conda_recipe/ -c bioconda -c conda-forge
conda install --use-local bactowise -c bioconda -c conda-forge
```

**WSL users:** If `conda build` fails with a syntax error near `(`:
```bash
export PATH=$CONDA_PREFIX/bin:/usr/bin:/bin
conda mambabuild --suppress-variables -c conda-forge -c bioconda conda_recipe/
```

---

## 2. Databases

BactoWise stores all databases under `~/.bactowise/databases/` and manages
them through the `bactowise db` command. The default configuration already
points to these paths — no manual edits needed.

### Required databases

BactoWise runs three annotation tools by default — Prokka, Bakta, and PGAP.
All three require their databases to be present before `bactowise run` can
proceed. A missing database for any active tool is flagged as an error.

**CheckM + Bakta (~4 GB combined):**
```bash
bactowise db download
```

Downloads:
- CheckM marker gene database (~2 GB) → `~/.bactowise/databases/checkm/`
- Bakta annotation database, light build (~2 GB) → `~/.bactowise/databases/bakta/db-light/`

The Bakta Singularity image (~500 MB) is pulled automatically during preflight
on first run — no separate step needed.

**PGAP supplemental data (~30 GB):**
```bash
bactowise db download --pgap
```

PGAP is part of every standard `bactowise run`. Its supplemental data must be
downloaded before the first run. Because of its size it is not bundled with
the core download — you must request it with `--pgap`. This command also
downloads `pgap.py` to `~/.bactowise/bin/pgap.py` automatically.

> **Disk space:** Plan for ~30 GB of storage for the PGAP data, plus ~100 GB
> of total working space when a PGAP job is running. The download itself
> takes significant time depending on your network.

If you want to run BactoWise without PGAP, use `--skip pgap` at runtime
rather than omitting the database download.

### Download individual databases

```bash
bactowise db download --checkm   # CheckM only
bactowise db download --bakta    # Bakta only
bactowise db download --pgap     # PGAP only (~30 GB)
```

### Force re-download

```bash
bactowise db download --force-db-download           # CheckM + Bakta
bactowise db download --checkm --force-db-download  # CheckM only
bactowise db download --pgap --force-db-download    # PGAP only
```

### Check database status

```bash
bactowise db status
```

This shows the status of all databases at their default locations:

```
✓  CheckM  → ~/.bactowise/databases/checkm
✓  Bakta   → ~/.bactowise/databases/bakta/db-light
✓  PGAP    → ~/.bactowise/databases/pgap
```

A missing database for any active tool is flagged as an error at preflight.

### Interrupted downloads

If a download is interrupted, just re-run the same command. BactoWise checks
for key marker files inside each database directory rather than just checking
whether the directory exists, so partial downloads are detected and re-run
automatically. For PGAP, the marker is a versioned `input-VERSION.BUILD/`
subdirectory written by pgap.py on successful completion.

---

## 3. Running the pipeline

### Get a test genome

```bash
efetch -db nucleotide -id NC_000908.2 -format fasta > mgenitalium.fasta
```

Or download directly from NCBI:
`https://www.ncbi.nlm.nih.gov/nuccore/NC_000908.2?report=fasta`

*M. genitalium G37* is a good test genome — at ~580 kb it is one of the
smallest known bacterial genomes and annotates quickly.

### Validate your config

Always run this first before a real annotation job:

```bash
bactowise validate
```

This checks that all required fields are present and well-formed without
invoking Singularity, creating conda environments, or touching databases.
It reads from `~/.bactowise/config/pipeline.yaml` automatically.

### Run

```bash
bactowise run -f mgenitalium.fasta -n "Mycoplasmoides genitalium"
```

The `-n`/`--organism` flag is mandatory. It must be a valid NCBI Taxonomy
name — check at https://www.ncbi.nlm.nih.gov/taxonomy. BactoWise passes
this to all annotation tools:

- **PGAP** — required as `-s`; used for genome size validation and marker
  gene selection. An incorrect name will cause PGAP to fail.
- **Prokka** — passed as `--genus` / `--species`; improves gene naming.
- **Bakta** — passed as `--genus` / `--species`; improves output labelling.

On first run, BactoWise will automatically:
- Create any missing conda environments (e.g. `checkm_env`, `prokka_env`)
- Pull the Bakta Singularity image (~500 MB, stored in `~/.bactowise/images/`)
- Attempt to download any missing databases — however, because the PGAP
  download is ~30 GB it is strongly recommended to run
  `bactowise db download --pgap` explicitly before your first run rather
  than relying on the automatic download.

### Specifying an output directory

By default, results are written to `./results/` in the current working
directory. Use `-o`/`--output` to write to a different location:

```bash
bactowise run -f mgenitalium.fasta -n "Mycoplasmoides genitalium" -o /scratch/my_project
```

The directory is created automatically if it does not exist. This is
particularly useful on HPC clusters where you want results on a scratch
filesystem, or when running multiple genomes and keeping each run's output
in its own directory:

```bash
bactowise run -f genome1.fasta -n "Escherichia coli"        -o results/ecoli
bactowise run -f genome2.fasta -n "Staphylococcus aureus"   -o results/saureus
```

### Output layout

With all tools active (CheckM + Prokka + Bakta + PGAP), using the default
output directory or one specified with `-o`:

```
<output_dir>/
├── checkm/
│   ├── checkm_summary.tsv   ← completeness & contamination metrics
│   ├── checkm_out/          ← full CheckM output directory
│   └── logs/
│       └── checkm.log
├── prokka/
│   ├── prokka_output.gff
│   ├── prokka_output.gbk
│   └── logs/
│       └── prokka.log
├── bakta/
│   ├── *.gff3
│   ├── *.gbff
│   └── logs/
│       └── bakta.log
├── pgap/                    ← only present when PGAP is active
│   ├── run_<timestamp>/     ← pgap.py creates a timestamped output directory
│   │   ├── annot.gff
│   │   ├── annot.gbk
│   │   └── cwltool.log      ← detailed pgap.py execution log
│   └── logs/
│       └── pgap.log
└── consensus/               ← Stage 3: BactoWise Consensus Engine
    ├── stage3_input/        ← staging folder (kept for debugging)
    │   ├── bakta_annotation.gff3
    │   ├── prokka_annotation.gff
    │   ├── pgap_annotation.gff
    │   └── <genome>.fasta
    ├── Master_Table_Annotation.xlsx
    ├── <prefix>.gff3
    ├── <prefix>.gbk
    ├── <prefix>.faa
    ├── <prefix>.fna
    ├── summary_report.txt
    ├── pipeline.log
    └── logs/
        └── consensus.log
amrfinderplus/               ← Stage 4: supplementary (present unless --skip stage_4)
    ├── amrfinderplus_results.tsv
    └── logs/
        └── amrfinderplus.log
phigaro/                     ← Stage 4: supplementary (present unless --skip stage_4)
    ├── phigaro_output.phg.tsv
    ├── phigaro_output.phg.gff
    └── logs/
        └── phigaro.log
```

---

## 4. Skipping stages

Two stages are skippable: stage 1 (QC) and stage 4 (supplementary annotations).
Stages 2 (annotation) and 3 (consensus) are core and cannot be skipped.

```bash
# Skip QC
bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_1

# Skip supplementary annotations (stage 4)
bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_4

# Skip both
bactowise run -f genome.fasta -n "Escherichia coli" --skip stage_1 --skip stage_4
```

**When to skip stage 1:**
- The genome has already been assessed and you're confident in its quality
- You are running a quick test and want to skip the ~2 GB CheckM database download
- You have QC results from another tool and just want annotation

**When to skip stage 4:**
- You only need the core annotation outputs and don't require AMR or other supplementary results
- Running on a time-constrained system and want the fastest possible run

**Attempting to skip stages 2 or 3 raises an error immediately:**
```
✗ Stage(s) [2] cannot be skipped.
  Skippable stages: 1 (QC) and 4 (supplementary).
  Stages 2 (annotation) and 3 (consensus) are core and cannot be skipped.
```

**Combining --skip stage_1 with --gff** (the maximalist use case):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --skip stage_1 \
  --gff pgap:/path/to/pgap.gff
```

---

## 5. Bypassing annotation with pre-computed GFF files

If you already have annotation results from a previous run — or from running
Bakta, Prokka, or PGAP independently — you can provide those GFF files
directly using `--gff`. Any tools you provide a GFF for are bypassed
entirely; the remaining annotation tools run normally. CheckM still runs as
normal unless you also pass `--skip checkm`.

### How it works

- You can provide a GFF for **any number** of annotation tools — one, two,
  or all three.
- Tools you provide a GFF for are bypassed — no runner is created, no
  preflight check is run, and no database download is triggered for them.
- Tools you do **not** provide a GFF for run normally and compute their
  annotation from scratch.

### Usage

**Bypass all three annotation tools** (full bypass — nothing annotates):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff \
  --gff pgap:/path/to/pgap.gff
```

**Bypass only Prokka** (Bakta and PGAP still run and annotate):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff prokka:/path/to/prokka.gff
```

**Bypass Bakta and Prokka** (PGAP still runs):
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff
```

Each `--gff` flag takes the format `tool:path`. The tool name must match the
name in the active config exactly (e.g. `bakta`, `prokka`, `pgap`).

You can also combine `--gff` with `--skip checkm` to bypass QC as well:

```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --skip checkm \
  --gff bakta:/path/to/bakta.gff3
```

### What happens to the provided files

BactoWise copies each GFF file into the standard output directory for that
tool so that downstream steps always find results in the same place,
regardless of whether annotation was run or provided:

```
results/
├── bakta/
│   └── provided_bakta.gff3    ← copied from your --gff path
├── prokka/
│   └── provided_prokka.gff    ← copied from your --gff path
└── pgap/
    └── run_<timestamp>/       ← computed normally (no GFF provided)
        └── annot.gff
```

### What the pipeline summary shows

```
  ✓  checkm          → results/checkm
  ↩  bakta           → GFF provided
  ↩  prokka          → GFF provided
  ✓  pgap            → results/pgap/run_<timestamp>
```

### Error cases caught before anything runs

**GFF for a tool not in the config or not an annotation tool:**
```
✗ --gff provided for unknown or non-annotation tool(s): chekm.
  Annotation tools in this config: bakta, pgap, prokka
```

**Same tool in both --gff and --skip:**
```
✗ Tool(s) appear in both --gff and --skip: bakta.
  Use --skip to exclude a tool entirely, or --gff to provide its
  pre-computed output — not both.
```

**GFF file not found on disk:**
```
✗ GFF file for 'pgap' not found: /path/to/pgap.gff
```

---

## 6. Understanding QC output

`results/checkm/checkm_summary.tsv` contains one row per genome:

| Column | Description |
|---|---|
| `Completeness` | % of expected marker genes found — higher is better |
| `Contamination` | % of marker genes found more than once — lower is better |
| `Strain heterogeneity` | % of contamination attributable to closely related strains |

**Default pass criteria:**
- Completeness > 95%
- Contamination < 5%

If either threshold is not met, BactoWise prints a warning and continues.
Annotation results should be interpreted with caution for low-quality assemblies.

QC thresholds can be adjusted in the installed config (`~/.bactowise/config/pipeline.yaml`):

```yaml
- name: checkm
  qc_criteria:
    completeness: 90.0   # relax for difficult genomes
    contamination: 10.0
```

---

## 7. Stage 3 — BactoWise Consensus Engine

Stage 3 runs automatically after all three stage 2 annotation tools (Bakta,
Prokka, PGAP) complete. It merges their outputs into a single high-confidence
consensus annotation.

### What it does

The consensus engine resolves disagreements between the three annotation tools
by computing confidence scores and consensus levels (e.g. `Consensus_2/3`,
`Consensus_3/3`). It produces a comprehensive annotation table alongside
standard bioinformatics output formats compatible with Geneious, SnapGene, and
downstream pangenome tools like Panaroo.

### Inputs (staged automatically by BactoWise)

BactoWise collects the GFF outputs from stage 2 into a staging folder
(`<output_dir>/consensus/stage3_input/`) and renames them with tool-name
prefixes that the engine requires:

| Staged filename | Source |
|---|---|
| `bakta_annotation.gff3` | Bakta stage 2 output (or `--gff bakta:` bypass) |
| `prokka_annotation.gff` | Prokka stage 2 output (or `--gff prokka:` bypass) |
| `pgap_annotation.gff` | PGAP stage 2 output (or `--gff pgap:` bypass) |
| `<genome>.fasta` | Original input FASTA |

The staging folder is kept after the run for debugging purposes.

### Outputs

All outputs are written to `<output_dir>/consensus/`:

| File | Description |
|---|---|
| `Master_Table_Annotation.xlsx` | Primary consensus table with confidence scores and functional categories |
| `<prefix>.gff3` | Cleaned coordinates compatible with Geneious and SnapGene |
| `<prefix>.gbk` | GenBank flat file with full sequences and feature qualifiers |
| `<prefix>.faa` | Protein FASTA (high-confidence CDS only; excludes pseudogenes and sequences < 90 bp) |
| `<prefix>.fna` | Nucleotide CDS sequences |
| `summary_report.txt` | Pipeline statistics, HP rates, and tool agreement |
| `pipeline.log` | Full execution history and error tracking |

### Dependencies

The consensus engine requires Python with `pandas` and `openpyxl`. BactoWise
creates a dedicated `consensus_env` conda environment on first run — no manual
setup is needed.

### Stage 3 cannot be skipped

The consensus engine is the core output of BactoWise and cannot be skipped.
Attempting `--skip stage_3` raises an error immediately.

### Stage 3 requires all three stage 2 tools

If any stage 2 tool fails, the pipeline exits before reaching stage 3. The
`--gff` bypass can be used to provide pre-computed GFF files for any failed or
previously-run tools so that stage 3 can proceed:

```bash
# Provide a pre-computed PGAP result and let Bakta and Prokka run normally
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" \
  --gff pgap:/path/to/pgap/annot.gff
```

---

## 8. Stage 4 — Supplementary Annotations

Stage 4 provides additional biological context beyond the core annotation. It
is **skippable** with `--skip stage_4` and runs after stage 3 completes. All
stage 4 tools depend on the consensus engine output.

### AMRFinderPlus — antimicrobial resistance genes and point mutations

AMRFinderPlus scans the genome for acquired AMR genes, virulence factors,
stress resistance genes, and — for supported taxa — known point mutations
associated with resistance.

**Inputs used:**
- Genome FASTA (original `-f` input)
- `<output_dir>/consensus/GENE.faa` — protein FASTA from stage 3

BactoWise runs AMRFinderPlus in combined nucleotide + protein mode for maximum
sensitivity without the fragility of GFF-linked mode.

**Output:**
```
<output_dir>/amrfinderplus/
    amrfinderplus_results.tsv   tab-delimited AMR findings
    logs/amrfinderplus.log
```

**Configuring point mutation detection:**

AMRFinderPlus supports taxon-specific point mutation screening for a subset of
organisms. To enable it, set `organism` in `pipeline.yaml` to one of the values
returned by `amrfinder --list_organisms`. This is separate from the `-n` organism
name — it must match AMRFinderPlus's own taxon list exactly.

```yaml
- name: amrfinderplus
  params:
    plus: true
    organism: "Escherichia"   # enables point mutation detection
```

Supported organism values include: `Acinetobacter_baumannii`, `Campylobacter`,
`Clostridioides_difficile`, `Enterococcus_faecalis`, `Enterococcus_faecium`,
`Escherichia`, `Klebsiella`, `Neisseria`, `Pseudomonas_aeruginosa`,
`Salmonella`, `Staphylococcus_aureus`, `Staphylococcus_pseudintermedius`,
`Streptococcus_agalactiae`, `Streptococcus_pneumoniae`, `Streptococcus_pyogenes`,
`Vibrio_cholerae`. Omit `organism` entirely if your organism is not in this list.

**Database:** downloaded automatically via `amrfinder -u` during preflight.
No manual setup required.

**Skipping stage 4:**
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_4
```

### Phigaro — prophage region detection

Phigaro detects prophage regions embedded in bacterial genome assemblies using
a two-step approach: Prodigal calls ORFs from the raw assembly, then pVOG HMM
profiles annotate phage-associated genes, and a smoothing window algorithm
identifies regions with high phage gene density.

**Input used:** The original genome FASTA (`-f`) — no stage 2 or stage 3
outputs are required. Phigaro performs its own gene calling internally.

**Setup:** `phigaro-setup` downloads the pVOG HMM database (~20 MB) to
`~/.phigaro/` on first run. BactoWise runs this automatically during preflight
if the config file is not yet present.

**Output:**
```
<output_dir>/phigaro/
    phigaro_output.phg.tsv   prophage coordinates (contig, start, end)
    phigaro_output.phg.gff   prophage regions in GFF3 format
    logs/phigaro.log
```

**Skipping stage 4:**
```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_4
```

---

## 9. Downstream analysis — pangenome with Panaroo

Panaroo is a pangenome pipeline that takes GFF annotation files as input and
computes core and accessory genome statistics across multiple bacterial isolates.
BactoWise does not orchestrate Panaroo — you run it separately after BactoWise
has finished. The GFF files produced by Bakta and Prokka are directly compatible
with Panaroo's input requirements.

### Which output files to use

After a BactoWise run, the annotation outputs are at:

```
results/
├── bakta/
│   └── *.gff3               ← Bakta output
├── prokka/
│   └── prokka_output.gff    ← Prokka output
└── pgap/                    ← PGAP output (if active)
    └── run_<timestamp>/
        └── annot.gff
```

When combining annotations from multiple isolates — for instance, one annotated
with Bakta and others with Prokka — pass all the GFF files together to Panaroo
in a single command. Panaroo handles mixed Bakta/Prokka/PGAP input without issue.

### Installing Panaroo

Panaroo requires Python 3.9 and has its own dependency constraints, so a
dedicated environment is recommended rather than installing into your BactoWise
environment.

```bash
conda create -n panaroo_env python=3.9 -y
conda activate panaroo_env
conda install -c conda-forge -c bioconda -c defaults 'panaroo>=1.3'
```

### Running Panaroo

```bash
conda activate panaroo_env

panaroo \
  -i /path/to/results/bakta/*.gff3 \
      /path/to/results/prokka/*.gff \
      /path/to/other/annotations/*.gff \
  -o /path/to/panaroo_output \
  --clean-mode strict \
  -t 4
```

`--clean-mode strict` is appropriate for high-quality assemblies. Use `moderate`
or `sensitive` if working with lower-quality or more divergent genomes. See the
[Panaroo documentation](https://gtonkinhill.github.io/panaroo) for details on
all available options.

---

## 10. Troubleshooting

| Error | Fix |
|---|---|
| `singularity: command not found` | Run `module load singularity` or install Apptainer: `sudo apt install -y apptainer` |
| `Database not found at ~/.bactowise/databases/bakta` | Run `bactowise db download --bakta` |
| `CheckM database path not found` | Run `bactowise db download --checkm` |
| `checkm_env not found` | BactoWise creates it automatically on first run — check preflight output |
| `prokka not found on PATH` | BactoWise creates `prokka_env` automatically on first run — check preflight output |
| `bactowise: command not found` | Run `conda activate <your-env>` first |
| CheckM fails silently | Check `results/checkm/logs/checkm.log` |
| Download interrupted | Re-run the same `bactowise db download` command — partial downloads are detected automatically |
| `pgap.py not found` | Run `bactowise db download --pgap` — this downloads pgap.py and the supplemental data automatically |
| `PGAP supplemental data not found` | Run `bactowise db download --pgap` (~30 GB). This is required for every standard run — use `--skip pgap` if you want to run without it. |
| PGAP fails with cgroups error | This is a VM/HPC kernel issue with CPU limits. It is handled automatically — BactoWise does not pass `-c` to pgap.py. If it still occurs, check `results/pgap/run_<timestamp>/cwltool.log` |
| PGAP fails with exit code 255 | Check `results/pgap/run_<timestamp>/cwltool.log` for the detailed Singularity error |
| `No module named 'pkg_resources'` (CheckM) | Delete `checkm_env` and rerun: `conda env remove -n checkm_env -y && bactowise run -f genome.fasta` |

---

# Developer Guide

## 1. pipeline.yaml field reference

Every tool block in the config is validated by Pydantic before anything
runs. Unknown fields are rejected with a clear error message.

### Top-level fields

| Field | Type | Default | Description |
|---|---|---|---|
| `tools` | list | required | Ordered list of tool definitions |
| `output_dir` | path | `./results` | Root directory for all tool outputs |
| `threads` | int | `4` | Global thread count (tools may override this in their `params`) |

### Per-tool fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | string | required | Tool name — must match the binary name for conda tools |
| `version` | string | required | Expected version — checked at preflight, mismatch warns but does not fail |
| `runtime` | `conda` \| `singularity` \| `docker` \| `pgap` | required | How the tool is executed |
| `role` | `qc` \| `annotation` | `annotation` | `qc` tools gate downstream stages and trigger QC warnings |
| `depends_on` | list[str] | `[]` | Tools that must complete before this one starts |
| `image` | string | `name:version` | Docker image ref — required for `runtime: docker`, auto-filled if omitted |
| `database.path` | path | — | Path to the tool's database directory, mounted read-only into Docker |
| `database.type` | `light` \| `full` | `full` | Passed to `bakta_db download` |
| `conda_env.name` | string | — | Name of the dedicated conda environment to create and run the tool in |
| `conda_env.channels` | list[str] | `[bioconda, conda-forge]` | Conda channels used when creating the environment |
| `conda_env.dependencies` | list[str] | `[]` | Extra packages to install alongside the tool (e.g. `python=3.8`) |
| `qc_criteria.completeness` | float | `95.0` | Minimum completeness % — only valid when `role: qc` |
| `qc_criteria.contamination` | float | `5.0` | Maximum contamination % — only valid when `role: qc` |
| `params` | dict | `{}` | Tool-specific CLI flags, passed as `--key value` |

### Validation rules enforced at config load time

- `conda_env` is only valid for `runtime: conda`
- `qc_criteria` is only valid for `role: qc`
- Every name listed in `depends_on` must exist in the `tools` list
- At least one tool must be defined

---

---

## 2. Modifying pipeline.yaml locally

`pipeline.yaml` is the single file that controls which tools run, which
versions are used, and what parameters they receive. For most users it
works out of the box without any edits. The modifications below are
low-effort and well-tested — each one requires changing only one or two
lines.

### Relaxing QC thresholds

The default thresholds (completeness > 95%, contamination < 5%) can be
too strict for some genomes, such as draft assemblies or environmental
isolates. Adjust them under the `checkm` block:

```yaml
- name: checkm
  qc_criteria:
    completeness: 90.0   # lower if working with difficult genomes
    contamination: 10.0
```

BactoWise will warn but continue if either threshold is not met regardless
of these values — the thresholds control when the warning fires, not
whether annotation proceeds.

### Changing the number of threads

Each tool picks up its thread count from its own `params` block. To speed
up a run on a machine with more cores, increase `threads` (or `cpus` for
Prokka) under each tool:

```yaml
- name: checkm
  params:
    threads: 8

- name: prokka
  params:
    cpus: 8

- name: bakta
  params:
    threads: 8
```

### Specifying genus and species for Prokka

Prokka produces better gene naming when it knows the organism. Set `genus`
and `species` under Prokka's `params` block:

```yaml
- name: prokka
  params:
    genus: "Mycoplasma"
    species: "genitalium"
    kingdom: Bacteria
    cpus: 4
```

These are passed directly to Prokka as `--genus`, `--species`, and
`--kingdom` flags. Omitting them is valid — Prokka falls back to its
general bacterial database.

### Changing the CheckM workflow

CheckM supports two modes. The default (`taxonomy_wf`) is fast and
requires ~2 GB of database. The more accurate `lineage_wf` requires the
full ~40 GB database but gives per-lineage marker sets:

```yaml
- name: checkm
  params:
    mode: lineage_wf
    threads: 4
```

Download the larger database the same way (`bactowise db download --checkm`)
and point `database.path` to the same directory — BactoWise runs
`checkm data setRoot` automatically on every preflight.

### Specifying the organism name

The organism name is passed via `-n`/`--organism` on the command line and
flows automatically to all annotation tools:

- **PGAP** — passed as `-s`; used for genome size validation and annotation
  marker selection. Must be a valid NCBI Taxonomy name.
- **Prokka** — split on the first space into `--genus` and `--species`;
  improves gene naming. Prokka is tolerant of approximate names.
- **Bakta** — split on the first space into `--genus` and `--species`;
  used for output file labelling only.

To verify that a name is valid in NCBI Taxonomy:
1. Go to https://www.ncbi.nlm.nih.gov/taxonomy
2. Search for the organism name
3. Confirm the result has rank `genus` or more specific

```bash
# Correct usage
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium"
bactowise run -f genome.fasta -n "Escherichia coli"
bactowise run -f genome.fasta -n "Staphylococcus"   # genus only is accepted
```

> **Note on CPU limits:** BactoWise does not pass a CPU limit to pgap.py
> because doing so causes a cgroups error on some cloud VMs and HPC nodes.
> PGAP will use all available CPUs by default. If you need to limit resource
> usage, use `--skip pgap` and invoke pgap.py manually for that step.

### Pointing to a custom database location

If you downloaded the Bakta or CheckM databases to a non-default path,
update the `database.path` for the relevant tool:

```yaml
- name: bakta
  database:
    path: "/scratch/my_project/bakta/db-light"
    type: light

- name: checkm
  database:
    path: "/scratch/my_project/checkm_db"
```

`bactowise db status` only checks the default location
(`~/.bactowise/databases/`). Custom paths are verified at runtime when
you run `bactowise run`.

## 3. Adding a new tool

The pipeline is designed so that adding a new tool requires a config entry and
— if the tool needs special invocation logic beyond the generic pattern — a new
runner class. No other files need to change.

### Step 1 — Add a tool block to pipeline.yaml

**Conda tool example:**
```yaml
- name: your_tool
  version: "2.1.0"
  runtime: conda
  depends_on: [checkm]           # runs after checkm completes
  conda_env:
    name: "your_tool_env"
    channels: [bioconda, conda-forge]
    dependencies: [python=3.10]  # only needed if there are version conflicts
  params:
    threads: 4
    your-flag: value
```

**Docker tool example:**
```yaml
- name: your_tool
  version: "2.1.0"
  runtime: docker
  depends_on: [checkm]
  image: "org/your_tool:2.1.0"
  database:
    path: "~/.bactowise/databases/your_tool_db"
    type: light
  params:
    threads: 4
```

### Step 2 — Handle the tool's command in the appropriate runner

#### If the tool follows the generic pattern

For conda tools, `CondaToolRunner._build_command()` falls back to:
```
your_tool --input <fasta> --outdir <output_dir> [--key value ...]
```

For Docker tools, `DockerToolRunner._build_command()` falls back to:
```
--input /input/<fasta> --output /output
```

If your tool happens to use these conventions, no code changes are needed.

#### If the tool needs custom argument ordering

Add a branch in the appropriate runner. For a conda tool, edit
`bactowise/runners/conda_runner.py`:

```python
def _build_command(self, fasta: Path) -> list[str]:
    if self.config.name == "prokka":
        return self._prokka_command(fasta)
    if self.config.name == "your_tool":           # add this
        return self._your_tool_command(fasta)
    # generic fallback
    ...

def _your_tool_command(self, fasta: Path) -> list[str]:
    tool_args = [
        "--genome", str(fasta),
        "--out",    str(self.output_dir),
    ]
    for key, val in self.config.params.items():
        tool_args += [f"--{key}", str(val)]
    return self._conda_run_cmd(tool_args)
```

For a Docker tool, add a branch in `bactowise/runners/docker_runner.py`:

```python
def _build_command(self, fasta: Path) -> str:
    if self.config.name == "bakta":
        return self._bakta_command(fasta)
    if self.config.name == "your_tool":           # add this
        return self._your_tool_command(fasta)
    ...

def _your_tool_command(self, fasta: Path) -> str:
    cmd = f"--genome /input/{fasta.name} --outdir /output"
    for key, val in self.config.params.items():
        cmd += f" --{key} {val}"
    return cmd
```

#### If the tool needs entirely custom preflight or run logic

Create a dedicated runner class following the existing pattern:

```python
# bactowise/runners/your_tool_runner.py
from bactowise.runners.conda_runner import CondaToolRunner  # or DockerToolRunner

class YourToolRunner(CondaToolRunner):
    def preflight(self) -> None:
        # custom checks — database setup, licence validation, etc.
        super().preflight()

    def run(self, fasta: Path) -> Path:
        # custom execution logic
        ...
```

Then register it in `bactowise/runners/factory.py`:

```python
from bactowise.runners.your_tool_runner import YourToolRunner

@staticmethod
def create(tool_config: ToolConfig, output_dir: Path) -> BaseRunner:
    if tool_config.name == "checkm":
        return CheckMRunner(tool_config, output_dir)
    if tool_config.name == "your_tool":           # add this
        return YourToolRunner(tool_config, output_dir)
    if tool_config.runtime == "conda":
        return CondaToolRunner(tool_config, output_dir)
    ...
```

### Step 3 — Add tests

Add a test class to `tests/test_bactowise.py` that covers at minimum:
- Config parses correctly with the new tool block
- `RunnerFactory.create()` returns the right runner type
- Any custom command-building logic produces the expected argument list

### Step 4 — Run the test suite

```bash
bash run_tests.sh
```
