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
    - [AMRFinderPlus](#amrfinderplus--antimicrobial-resistance-genes-and-point-mutations)
    - [Phigaro](#phigaro--prophage-region-detection)
    - [Platon](#platon--plasmid-contig-classification-and-characterisation)
    - [MEFinder](#mefinder-mobileelemenfinder--transposon-and-is-element-detection)
    - [EggNOG-mapper](#eggnog-mapper--go-terms-kegg-pathways-and-cog-annotation)
    - [SPIFinder](#spifinder--salmonella-pathogenicity-island-detection)
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

PGAP runs inside a Singularity container. Singularity and Apptainer are the
same runtime — Apptainer is the actively maintained community fork and is
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

BactoWise stores all managed databases under `~/.bactowise/databases/` and
tracks them through the `bactowise db` command. The default configuration
already points to these paths — no manual edits needed.

> **Total disk space required: ~223 GB**
> ~163 GB for all databases combined, plus ~60 GB working space during a PGAP run
> (NCBI documents ~100 GB total for PGAP supplemental data and working space combined).
> Ensure your filesystem has sufficient free space before starting.

### Stages 1–2 databases (~110 GB)

**CheckM (~1.4 GB):**
```bash
bactowise db download --checkm
```
Downloaded to `~/.bactowise/databases/checkm/`.

**Bakta full database (~71 GB):**
```bash
bactowise db download --bakta
```
Downloaded to `~/.bactowise/databases/bakta/db/`.
Bakta runs from a BactoWise-managed conda environment by default — no container image is required.

**PGAP supplemental data (~38 GB):**
```bash
bactowise db download --pgap
```
Downloaded to `~/.bactowise/databases/pgap/`. Because of its size it must be
requested separately. This command also downloads `pgap.py` to
`~/.bactowise/bin/pgap.py` automatically.

> **Disk space:** NCBI documents ~100 GB total for PGAP supplemental data and
> working space combined. With 38 GB already on disk as the database, plan for
> ~60 GB additional working space during a PGAP run.

### Stage 4 databases (~54 GB combined)

Stage 4 databases are downloaded automatically on first run if not already
present. Because of their size, pre-downloading is strongly recommended:

**Platon plasmid database (~2.8 GB):**
```bash
bactowise db download --platon
```
Stored at `~/.bactowise/databases/platon/db/`. Downloaded from Zenodo.

**EggNOG-mapper database (~48 GB):**
```bash
bactowise db download --eggnog
```
Stored at `~/.bactowise/databases/eggnog/`. Includes `eggnog.db` (~43 GB
SQLite annotation database) and `eggnog_proteins.dmnd` (~4 GB DIAMOND search
database). Downloads support automatic resume — if the connection drops,
re-running the same command picks up from the last completed byte.
This database is substantially larger than the published documentation suggests;
plan accordingly.

**Phigaro pVOG profiles (~1.6 GB):**
Stored at `~/.bactowise/databases/phigaro/`. Downloaded automatically by
`phigaro-setup` during preflight. No separate download command is needed.

**SPIFinder tool and database (~3 MB, git clone):**
```bash
bactowise db download --spifinder
```
Stored at `~/.bactowise/databases/spifinder/`. Both the tool script and its
BLAST database are cloned from Bitbucket via git. This is only installed when
the organism genus is Salmonella — BactoWise skips it entirely for all other
organisms. Requires `git` to be available on your PATH.

**AMRFinderPlus and MEFinder databases:**
Both are self-managed inside their respective conda environments and are not
tracked in `~/.bactowise/databases/`:
- AMRFinderPlus: downloaded by `amrfinder -u` into `amrfinderplus_env` during preflight
- MEFinder: bundled with the pip package inside `mefinder_env`

### Download all databases

```bash
bactowise db download
```

### Download individual databases

```bash
bactowise db download --checkm     # CheckM only (~1.4 GB)
bactowise db download --bakta      # Bakta only (~71 GB)
bactowise db download --pgap       # PGAP only (~38 GB)
bactowise db download --platon     # Platon only (~2.8 GB)
bactowise db download --eggnog     # EggNOG only (~48 GB)
bactowise db download --spifinder  # SPIFinder only (~3 MB, git clone)
```

### Force re-download

```bash
bactowise db download --force-db-download               # all managed databases
bactowise db download --checkm --force-db-download
bactowise db download --bakta --force-db-download
bactowise db download --pgap --force-db-download
bactowise db download --platon --force-db-download
bactowise db download --eggnog --force-db-download
bactowise db download --spifinder --force-db-download   # re-clones from Bitbucket
```

### Check database status

```bash
bactowise db status
```

Output groups databases by pipeline stage:

```
Stage 1 — QC
  ✓  CheckM   → ~/.bactowise/databases/checkm            (~1.4 GB)

Stage 2 — Annotation
  ✓  Bakta    → ~/.bactowise/databases/bakta/db          (~71 GB)
  ✓  PGAP     → ~/.bactowise/databases/pgap              (~38 GB)

Stage 4 — Supplementary
  ✓  Phigaro       → ~/.bactowise/databases/phigaro      (~1.6 GB)
  ✓  Platon        → ~/.bactowise/databases/platon/db    (~2.8 GB)
  ✓  EggNOG        → ~/.bactowise/databases/eggnog       (~48 GB)
  ✓  SPIFinder     → ~/.bactowise/databases/spifinder    (~3 MB, Salmonella only)
  ~  AMRFinderPlus → database managed inside amrfinderplus_env (not tracked here)
  ~  MEFinder      → database bundled with pip install inside mefinder_env (not tracked here)
```

### Interrupted downloads

BactoWise checks for key marker files inside each database directory — partial
downloads are detected and re-run automatically rather than silently skipping.
For large databases (EggNOG, PGAP), BactoWise uses HTTP range requests so
interrupted downloads resume from the last completed byte rather than restarting.

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
- Create the Bakta conda environment automatically when needed
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

### Controlling thread count

Use `--threads` to set the number of CPU threads used by all tools. This is
the recommended way to adjust parallelism — it overrides the default of 4
set in `pipeline.yaml` without modifying the config file:

```bash
bactowise run -f genome.fasta -n "Escherichia coli" --threads 8
bactowise run -f genome.fasta -n "Escherichia coli" --threads 16
```

The resolved thread count is shown at startup:

```
Threads  : 8  (--threads override)
```

When `--threads` is not passed, the value from `pipeline.yaml` is used
(default: 4). Individual tools can still be pinned to a specific thread
count via their `params` block in the config — see
[Changing the number of threads](DOCS.md#changing-the-number-of-threads)
in the Developer Guide.

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
├── pgap/
│   ├── run_<timestamp>/     ← pgap.py creates a timestamped output directory
│   │   ├── annot.gff
│   │   ├── annot.gbk
│   │   └── cwltool.log      ← detailed pgap.py execution log
│   └── logs/
│       └── pgap.log
├── consensus/               ← Stage 3: BactoWise Consensus Engine
│   ├── stage3_input/        ← staging folder (kept for debugging)
│   │   ├── bakta_annotation.gff3
│   │   ├── prokka_annotation.gff
│   │   ├── pgap_annotation.gff
│   │   └── <genome>.fasta
│   ├── Master_Table_Annotation.xlsx
│   ├── GENE.gff3
│   ├── GENE.gbk
│   ├── GENE.faa             ← used by EggNOG-mapper in stage 4
│   ├── GENE.fna
│   ├── summary_report.txt
│   ├── pipeline.log
│   └── logs/
│       └── consensus.log
├── amrfinderplus/           ← Stage 4 (present unless --skip stage_4)
│   ├── amrfinderplus_results.tsv
│   └── logs/
│       └── amrfinderplus.log
├── phigaro/                 ← Stage 4
│   ├── phigaro_output.phg.tsv
│   ├── phigaro_output.phg.gff
│   └── logs/
│       └── phigaro.log
├── platon/                  ← Stage 4
│   ├── platon_output.tsv         ← plasmid contig summary
│   ├── platon_output.json        ← comprehensive per-contig results
│   ├── platon_output_plasmid.fasta
│   ├── platon_output_chromosome.fasta
│   └── logs/
│       └── platon.log
├── mefinder/                ← Stage 4
│   ├── mefinder_output.csv       ← MGE predictions with quality metrics
│   ├── mefinder_output.gff       ← MGE locations in GFF3 format
│   └── logs/
│       └── mefinder.log
├── spifinder/               ← Stage 4 (Salmonella only — absent for other organisms)
│   ├── spifinder_results.tsv     ← SPI hits with coverage and identity
│   ├── spifinder_results.json    ← full CGE-format results
│   ├── Hit_in_genome_seq.fsa     ← matched genomic sequences (FASTA)
│   └── logs/
│       └── spifinder.log
└── eggnogmapper/            ← Stage 4
    ├── eggnog_output.emapper.annotations   ← GO / KEGG / COG per gene (TSV)
    ├── eggnog_output.emapper.hits          ← raw DIAMOND hits
    ├── eggnog_output.emapper.seed_orthologs
    └── logs/
        └── eggnogmapper.log
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
five stage 4 tools run in parallel once stage 3 finishes.

```bash
bactowise run -f genome.fasta -n "Mycoplasmoides genitalium" --skip stage_4
```

---

### AMRFinderPlus — antimicrobial resistance genes and point mutations

AMRFinderPlus identifies acquired AMR genes, virulence factors, stress
resistance genes, and — for supported taxa — known chromosomal point mutations
associated with resistance phenotypes.

**Input:** The original genome FASTA (`-f`). No stage 2 or stage 3 outputs
are required.

**Database:** Downloaded automatically via `amrfinder -u` during preflight.
Stored inside the `amrfinderplus_env` conda environment — not tracked under
`~/.bactowise/databases/` (the tool manages its own data directory and provides
no flag to redirect it).

**Output:**
```
<output_dir>/amrfinderplus/
    amrfinderplus_results.tsv   — tab-delimited AMR findings
    logs/amrfinderplus.log
```

The TSV reports gene name, element type (AMR / VIRULENCE / STRESS / POINT),
contig, coordinates, strand, percent identity, percent coverage, and whether
the finding is a core or plus element.

**Configuring point mutation detection:**

Point mutation screening is only available for a specific set of clinically
relevant taxa. Set `organism` in `pipeline.yaml` to a value from
`amrfinder --list_organisms`:

```yaml
- name: amrfinderplus
  params:
    plus: true
    organism: "Escherichia"   # enables point mutation detection
```

Supported values include: `Acinetobacter_baumannii`, `Campylobacter`,
`Clostridioides_difficile`, `Enterococcus_faecalis`, `Enterococcus_faecium`,
`Escherichia`, `Klebsiella`, `Neisseria`, `Pseudomonas_aeruginosa`,
`Salmonella`, `Staphylococcus_aureus`, `Staphylococcus_pseudintermedius`,
`Streptococcus_agalactiae`, `Streptococcus_pneumoniae`, `Streptococcus_pyogenes`,
`Vibrio_cholerae`. Omit `organism` entirely if your organism is not in this list.

---

### Phigaro — prophage region detection

Phigaro identifies prophage regions embedded in bacterial genome assemblies.
It calls ORFs with Prodigal, annotates phage-associated genes against pVOG HMM
profiles, then applies a smoothing window to flag contiguous regions with high
phage gene density.

**Input:** The original genome FASTA (`-f`). Phigaro calls its own ORFs
internally — no stage 2 or stage 3 outputs are required.

**Database:** pVOG HMM profiles (~1.5 GB), downloaded automatically by
`phigaro-setup` during preflight to `~/.bactowise/databases/phigaro/pvog/`.
The config file is written to `~/.bactowise/databases/phigaro/config.yml`.
No manual setup is required.

**Output:**
```
<output_dir>/phigaro/
    phigaro_output.phg.tsv   — prophage coordinates (scaffold, start, end)
    phigaro_output.phg.gff   — prophage regions in GFF3 format
    logs/phigaro.log
```

---

### Platon — plasmid contig classification and characterisation

Platon distinguishes plasmid-borne contigs from chromosomal DNA using replicon
distribution scores (RDS) — a probabilistic measure of how biased a protein
family's distribution is between chromosomes and plasmids across a reference
database of sequenced genomes. Plasmid contigs are then characterised for
replication systems, mobilisation genes, conjugation machinery, oriT sequences,
and incompatibility groups.

**Input:** The original genome FASTA (`-f`). Platon uses Prodigal for ORF
calling and performs its own searches — no stage 2 or stage 3 outputs are
required.

**Database:** ~2.8 GB, downloaded automatically from Zenodo during preflight
to `~/.bactowise/databases/platon/db/`. Can be pre-downloaded with:
```bash
bactowise db download --platon
```

**Output:**
```
<output_dir>/platon/
    platon_output.tsv              — plasmid contig summary (one row per contig)
    platon_output.json             — comprehensive per-contig results
    platon_output_plasmid.fasta    — sequences of plasmid-classified contigs
    platon_output_chromosome.fasta — sequences of chromosomal contigs
    logs/platon.log
```

The TSV summary reports contig ID, length, coverage, RDS score, circular
status, and characterisation findings (replication genes, mobilisation genes,
oriT, conjugation, incompatibility groups, plasmid IDs).

**Configuring the classification mode:**

Platon supports three sensitivity modes. The default (`accuracy`) is the
recommended setting for most assemblies:

```yaml
- name: platon
  params:
    mode: accuracy        # sensitivity | accuracy | specificity
```

Use `sensitivity` for fragmented or low-coverage assemblies where some plasmid
contigs may be small and hard to classify. Use `specificity` when minimising
false positives is more important than recovering all plasmid contigs.

---

### MEFinder (MobileElementFinder) — transposon and IS element detection

MEFinder identifies mobile genetic elements (MGEs) in bacterial assemblies by
aligning contigs against the curated MGEdb reference database of known
transposons, insertion sequences (IS), integrons, and composite transposons.
It produces both tabular predictions and a GFF3 output for visualisation.

**Input:** The original genome FASTA (`-f`). No stage 2 or stage 3 outputs
are required.

**Database:** Bundled with the MobileElementFinder pip package inside the
`mefinder_env` conda environment (the MGEdb package). No separate download
or database path is needed — the database is available as soon as the env is
created.

**Installation note:** MEFinder is installed via pip inside `mefinder_env`
because it is not on bioconda. BLAST+ and KMA are installed via conda first
to provide pre-built binaries, then `pip install MobileElementFinder` adds the
tool and its database on top. BactoWise handles this automatically.

**Output:**
```
<output_dir>/mefinder/
    mefinder_output.csv   — MGE predictions with element type, coordinates,
                            quality score, and sequence identity
    mefinder_output.gff   — MGE locations in GFF3 format
    logs/mefinder.log
```

The CSV reports element name, type (transposon / IS element / integron),
contig, start, end, strand, identity, and coverage.

---

### EggNOG-mapper — GO terms, KEGG pathways, and COG annotation

EggNOG-mapper assigns Gene Ontology (GO) terms, KEGG pathway and module
memberships, COG functional categories, and eggNOG orthology group identifiers
to every protein in the consensus annotation. It does this by searching proteins
against the eggNOG DIAMOND database, identifying fine-grained orthologs in the
eggNOG hierarchy, and transferring functional annotations from those orthologs.

**Input:** `<output_dir>/consensus/GENE.faa` — the protein FASTA produced by
the stage 3 Consensus Engine. This is the only stage 4 tool that intentionally
uses a stage 3 output: the goal is to annotate every consensus gene identified
across Bakta, Prokka, and PGAP with biological context, so the consensus
protein set is the correct input.

**Database:** ~20 GB total, stored at `~/.bactowise/databases/eggnog/`:
- `eggnog.db` — main annotation SQLite database (~15 GB)
- `eggnog_proteins.dmnd` — DIAMOND search database (~4 GB)
- `eggnog.taxa.db` — taxonomy database

Downloaded directly from `eggnog5.embl.de` with automatic resume support.
Pre-download strongly recommended before your first full run:

```bash
bactowise db download --eggnog
```

If the download is interrupted, re-run the same command — it will resume from
the last completed byte.

**Output:**
```
<output_dir>/eggnogmapper/
    eggnog_output.emapper.annotations   — per-gene functional annotations (TSV)
    eggnog_output.emapper.hits          — raw DIAMOND hits
    eggnog_output.emapper.seed_orthologs — seed ortholog assignments
    logs/eggnogmapper.log
```

The annotations file has one row per gene with columns for: query (locus tag),
seed eggNOG ortholog, evalue, score, eggNOG OGs, max annotation level, COG
category, description, preferred name, GO terms, KEGG KO, KEGG pathway,
KEGG module, KEGG reaction, PFAMs, and BiGG reactions.

**Configuring the taxonomic scope:**

By default, EggNOG-mapper restricts ortholog transfers to bacterial clades
(`tax_scope: Bacteria`). This reduces false annotation transfers from distantly
related eukaryotic orthologs. Override in `pipeline.yaml` if needed:

```yaml
- name: eggnogmapper
  params:
    tax_scope: Bacteria    # Bacteria | Archaea | Eukaryota | Viruses
    go_evidence: all       # all | experimental | non-experimental
```

---

### SPIFinder — Salmonella Pathogenicity Island detection

SPIFinder screens Salmonella assemblies against a curated BLAST database of
15 known Salmonella Pathogenicity Islands (SPI-1 through SPI-14 and SPI-24),
identifying which islands are present and reporting BLAST coverage and identity
for each hit. It is a CGE tool developed at the Technical University of Denmark.

**Salmonella-only constraint:** SPIFinder only runs when the genus in
`-n`/`--organism` is Salmonella. For all other organisms BactoWise prints an
informational skip message and moves on — no output directory is created and
no time is spent on installation or database setup.

```
bactowise run -f genome.fasta -n "Salmonella enterica"    # SPIFinder runs
bactowise run -f genome.fasta -n "Escherichia coli"       # SPIFinder skipped
```

**Installation:** No Docker image or conda package exists for SPIFinder.
BactoWise installs it by git-cloning both the tool and its database from
Bitbucket into `~/.bactowise/databases/spifinder/` on first run, or
explicitly with:

```bash
bactowise db download --spifinder
```

This requires `git` to be available on your PATH. On HPC clusters:
```bash
module load git
```

**Database:** The SPI BLAST database is tiny (~3 MB) and is cloned alongside
the tool. No separate download step is needed.

**Output:**
```
<output_dir>/spifinder/
    spifinder_results.tsv       — SPI hits with coverage and identity per island
    spifinder_results.json      — full CGE-format results
    Hit_in_genome_seq.fsa       — matched genomic sequences (FASTA)
    logs/spifinder.log
```

**Configuring thresholds:**

Default thresholds are 95% identity and 60% coverage. These can be adjusted
in `pipeline.yaml`:

```yaml
- name: spifinder
  params:
    min_cov: 0.60     # minimum coverage  0–1 (default: 0.60)
    threshold: 0.95   # minimum identity  0–1 (default: 0.95)
```

Lowering `threshold` may detect more divergent SPI variants at the cost of
increased false positives. Raising `min_cov` reduces partial hits.

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
| `Database not found at ~/.bactowise/databases/bakta/db` | Run `bactowise db download --bakta` |
| `CheckM database path not found` | Run `bactowise db download --checkm` |
| `checkm_env not found` | BactoWise creates it automatically on first run — check preflight output |
| `prokka not found on PATH` | BactoWise creates `prokka_env` automatically on first run — check preflight output |
| `bactowise: command not found` | Run `conda activate <your-env>` first |
| CheckM fails silently | Check `results/checkm/logs/checkm.log` |
| Download interrupted | Re-run the same `bactowise db download --<tool>` command — partial downloads resume automatically |
| `pgap.py not found` | Run `bactowise db download --pgap` — downloads pgap.py and supplemental data automatically |
| `PGAP supplemental data not found` | Run `bactowise db download --pgap` (~30 GB). Use `--skip pgap` to run without it. |
| PGAP fails with cgroups error | VM/HPC kernel issue — handled automatically. If it persists, check `results/pgap/run_<timestamp>/cwltool.log` |
| PGAP fails with exit code 255 | Check `results/pgap/run_<timestamp>/cwltool.log` for the detailed Singularity error |
| `No module named 'pkg_resources'` (CheckM or MEFinder) | Delete the affected env and rerun: `conda env remove -n checkm_env -y` or `conda env remove -n mefinder_env -y` |
| EggNOG download stalls or fails at ~16% | Re-run `bactowise db download --eggnog` — the download resumes from the last completed byte automatically |
| `EggNOG database not found` | Run `bactowise db download --eggnog` (~48 GB). Pre-downloading is strongly recommended before the first full run. |
| `Platon database not found` | Run `bactowise db download --platon` (~2.8 GB) |
| `platon=latest` not found | Should not occur with the current version — if it does, `conda env remove -n platon_env -y` and rerun |
| `No module named 'mgedb'` (MEFinder) | Delete the env and rerun: `conda env remove -n mefinder_env -y && bactowise run ...` — BactoWise will reinstall it correctly |
| `phigaro-setup failed` | Run manually: `conda run -n phigaro_env phigaro-setup -c ~/.bactowise/databases/phigaro/config.yml -p ~/.bactowise/databases/phigaro/pvog -f --no-updatedb` |
| `emapper.py: command not found` | BactoWise creates `eggnogmapper_env` automatically — check preflight output |
| `Consensus FAA not found` for EggNOG-mapper | Ensure stage 3 completed successfully. Check `results/consensus/logs/consensus.log`. |
| `SPIFinder: Failed to clone` | Ensure `git` is on your PATH (`module load git` on HPC) and Bitbucket is reachable. Then re-run `bactowise db download --spifinder`. |
| `SPIFinder not found` / missing script | Run `bactowise db download --spifinder` to re-clone. If it persists, delete the directory and retry: `rm -rf ~/.bactowise/databases/spifinder && bactowise db download --spifinder` |
| SPIFinder skipped unexpectedly | SPIFinder only runs when genus is Salmonella. Check that `-n` starts with `Salmonella` (e.g. `-n "Salmonella enterica"`). |
| AMRFinderPlus exits with code 134 / "terminate called recursively" | This is a known blastn threading bug in the bioconda build. BactoWise always runs AMRFinderPlus with `-t 1` to avoid it — if you see this error on an older install, reinstall: `conda env remove -n amrfinderplus_env -y` and rerun. |

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
| `threads` | int | `4` | Global thread count — used by all tools unless overridden per-tool via `params.threads`. Can be overridden at runtime with `bactowise run --threads N`. |

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

### Stage 4 tool reference

| Tool | What it does | Input | Database | Location |
|---|---|---|---|---|
| **AMRFinderPlus** | AMR genes, virulence factors, point mutations | genome FASTA | auto-managed inside `amrfinderplus_env` | conda env internal |
| **Phigaro** | Prophage region detection | genome FASTA | pVOG HMM profiles (~1.6 GB) | `~/.bactowise/databases/phigaro/` |
| **Platon** | Plasmid contig classification and characterisation | genome FASTA | RDS database (~2.8 GB) | `~/.bactowise/databases/platon/db/` |
| **MEFinder** | Transposons, IS elements, integrons | genome FASTA | MGEdb, bundled with pip package | `mefinder_env` internal |
| **EggNOG-mapper** | GO terms, KEGG pathways, COG categories | consensus `GENE.faa` (stage 3) | eggNOG DIAMOND + SQLite (~48 GB) | `~/.bactowise/databases/eggnog/` |
| **SPIFinder** | Salmonella Pathogenicity Island detection | genome FASTA | SPI BLAST database (~3 MB, git clone) | `~/.bactowise/databases/spifinder/` |

EggNOG-mapper is the only stage 4 tool that uses a stage 3 output — it annotates
every protein in the consensus FASTA to provide biological context for each
consensus gene. See [Section 8](#8-stage-4--supplementary-annotations) in the
User Guide for full per-tool documentation.

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

The easiest way to change the thread count for all tools at once is the
`--threads` flag on `bactowise run`:

```bash
bactowise run -f genome.fasta -n "Escherichia coli" --threads 8
```

This overrides the `threads` value in `pipeline.yaml` for the duration of
that run without modifying the config file. The resolved thread count and
its source are shown in the startup banner:

```
Threads  : 8  (--threads override)
Threads  : 4  (pipeline.yaml default)
```

**Priority order for thread count:**
1. `--threads N` on the command line — overrides everything
2. `threads: N` in `pipeline.yaml` — used when `--threads` is not passed (default: 4)
3. Per-tool `params.threads` in `pipeline.yaml` — overrides the global value for that tool only

**Per-tool overrides** remain available for cases where one tool needs a
different thread count — for example, capping EggNOG-mapper to avoid
excessive memory use on a shared node:

```yaml
- name: eggnogmapper
  params:
    threads: 2   # run with fewer threads regardless of --threads or global default

- name: checkm
  params:
    threads: 8   # always use 8 for CheckM even if global is lower
```

**Note on AMRFinderPlus:** AMRFinderPlus is always run with a single thread
regardless of `--threads` or `pipeline.yaml`. The bioconda build has a known
threading bug that causes blastn to crash when `-t > 1`. The tool is fast
enough single-threaded for typical bacterial genomes.

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
    path: "/scratch/my_project/bakta/db"
    type: full

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
    type: full
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
