# BactoWise — Documentation

- [User Guide](#user-guide)
  - [1. Installation](#1-installation)
  - [2. Databases](#2-databases)
  - [3. Running the pipeline](#3-running-the-pipeline)
  - [4. Skipping tools](#4-skipping-tools)
  - [5. Bypassing annotation with pre-computed GFF files](#5-bypassing-annotation-with-pre-computed-gff-files)
  - [6. Understanding QC output](#6-understanding-qc-output)
  - [7. Downstream analysis — pangenome with Panaroo](#7-downstream-analysis--pangenome-with-panaroo)
  - [8. Troubleshooting](#8-troubleshooting)
- [Developer Guide](#developer-guide)
  - [1. pipeline.yaml field reference](#1-pipelineyaml-field-reference)
  - [2. Adding a new tool](#2-adding-a-new-tool)

---

# User Guide

## 1. Installation

### Docker

Bakta runs inside a Docker container. Install Docker Desktop for
[Mac or Windows](https://docker.com), or on Linux:

```bash
sudo apt install docker.io && sudo systemctl start docker
sudo usermod -aG docker $USER && newgrp docker
```

Verify:
```bash
docker run hello-world
# Should print: "Hello from Docker!"
```

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
them through the `bactowise db` command. The default `pipeline.yaml` already
points to these paths — no manual edits needed.

### Download all databases (recommended first step)

```bash
bactowise db download
```

Downloads:
- CheckM marker gene database (~2 GB) → `~/.bactowise/databases/checkm/`
- Bakta annotation database, light build (~2 GB) → `~/.bactowise/databases/bakta/db-light/`

### Download individual databases

```bash
bactowise db download --checkm   # CheckM only
bactowise db download --bakta    # Bakta only
```

### Force re-download

```bash
bactowise db download --force-db-download        # both
bactowise db download --checkm --force-db-download  # CheckM only
```

### Check database status

```bash
bactowise db status
```

### Interrupted downloads

If a download is interrupted, just re-run `bactowise db download`. BactoWise
checks for key marker files inside each database directory rather than just
checking whether the directory exists, so partial downloads are detected and
re-run automatically.

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

Always run this first after editing `pipeline.yaml`:

```bash
bactowise validate -c pipeline.yaml
```

This checks that all required fields are present and well-formed without
starting Docker, creating conda environments, or touching databases.

### Run

```bash
bactowise run -f mgenitalium.fasta -c pipeline.yaml
```

On first run, BactoWise will automatically:
- Create any missing conda environments (e.g. `checkm_env`, `prokka_env`)
- Pull any missing Docker images (e.g. `oschwengers/bakta`)

### Output layout

```
results/
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
└── bakta/
    ├── *.gff3
    ├── *.gbff
    └── logs/
        └── bakta.log
```

---

## 4. Skipping tools

Use `--skip` to exclude a tool from a run without editing the config file.
The flag accepts any tool name defined in `pipeline.yaml` and can be repeated.

```bash
# Skip QC if the genome has already been assessed
bactowise run -f genome.fasta -c pipeline.yaml --skip checkm

# Skip both annotation tools and run QC only
bactowise run -f genome.fasta -c pipeline.yaml --skip prokka --skip bakta
```

**What happens when you skip a tool:**
- The tool is excluded from preflight checks (Docker is not contacted, conda
  env is not inspected for that tool)
- Downstream tools that depend on the skipped tool are automatically unblocked
  and run as normal
- If the skipped tool has `role: qc`, a warning is printed before annotation
  begins to make clear that no quality gate was applied
- The final summary shows `⊘ checkm → skipped` so the record of the run is
  unambiguous

**Typos are caught immediately:**
```
✗ Error: Unknown tool(s) in --skip: chekm.
  Available tools: bakta, checkm, prokka
```

---

## 5. Bypassing annotation with pre-computed GFF files

If you already have annotation results from a previous run — or from running
Bakta, Prokka, or PGAP independently — you can provide those GFF files
directly and skip stage 2 entirely. CheckM still runs as normal unless you
also pass `--skip checkm`.

### All-or-nothing policy

You must provide GFF files for **all** annotation tools defined in your
pipeline, or **none** of them. Partial bypass — where some tools run and
others use pre-computed files — is not permitted and will be rejected with
a clear error before anything runs.

This policy exists to keep results consistent. Providing all files or none
ensures each run tells a coherent story. When you add PGAP to your pipeline
by uncommenting its block in `pipeline.yaml`, the required set automatically
grows to three. BactoWise derives the required set from the active tools at
runtime — no other configuration change is needed.

### Usage

```bash
# Bypass stage 2 — provide GFF for all annotation tools
bactowise run -f genome.fasta -c pipeline.yaml \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff
```

Each `--gff` flag takes the format `tool:path`. The tool name must match the
name in `pipeline.yaml` exactly (e.g. `bakta`, `prokka`, `pgap`).

You can also combine `--gff` with `--skip checkm` to bypass both stages:

```bash
bactowise run -f genome.fasta -c pipeline.yaml \
  --skip checkm \
  --gff bakta:/path/to/bakta.gff3 \
  --gff prokka:/path/to/prokka.gff
```

### What happens to the provided files

BactoWise copies each GFF file into the standard output directory for that
tool so that downstream steps always find results in the same place,
regardless of whether annotation was run or provided:

```
results/
├── bakta/
│   └── provided_bakta.gff3    ← copied from your --gff path
└── prokka/
    └── provided_prokka.gff    ← copied from your --gff path
```

### What the pipeline summary shows

```
  ⊘  checkm          → skipped
  ↩  bakta           → GFF provided
  ↩  prokka          → GFF provided
```

### Error cases caught before anything runs

**Partial bypass (missing tools):**
```
✗ GFF files must be provided for ALL annotation tools or NONE.
  Missing : prokka
  Annotation tools in this config: bakta, prokka
```

**Same tool in both --gff and --skip:**
```
✗ Tool(s) appear in both --gff and --skip: bakta.
  Use --skip to exclude a tool entirely, or --gff to provide its
  pre-computed output — not both.
```

**GFF file not found on disk:**
```
✗ GFF file for 'bakta' not found: /path/to/bakta.gff3
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

QC thresholds can be adjusted in `pipeline.yaml`:

```yaml
- name: checkm
  qc_criteria:
    completeness: 90.0   # relax for difficult genomes
    contamination: 10.0
```

---

## 7. Downstream analysis — pangenome with Panaroo

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
│   └── *.gff3          ← use this for Bakta output
└── prokka/
    └── prokka_output.gff   ← use this for Prokka output
```

When combining annotations from multiple isolates — for instance, one annotated
with Bakta and others with Prokka — pass all the GFF files together to Panaroo
in a single command. Panaroo handles mixed Bakta/Prokka input without issue.

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

## 8. Troubleshooting

| Error | Fix |
|---|---|
| `Cannot connect to Docker` | Open Docker Desktop and wait for the whale 🐳 to stop animating |
| `Database not found at ~/.bactowise/databases/bakta` | Run `bactowise db download --bakta` |
| `CheckM database path not found` | Run `bactowise db download --checkm` |
| `checkm_env not found` | Run `conda create -n checkm_env -c bioconda -c conda-forge checkm-genome=1.2.3 python=3.8 -y` |
| `prokka not found on PATH` | BactoWise creates `prokka_env` automatically on first run — check preflight output |
| `bactowise: command not found` | Run `conda activate <your-env>` first |
| CheckM fails silently | Check `results/checkm/logs/checkm.log` |
| Download interrupted | Re-run `bactowise db download` — partial downloads are detected automatically |

---

# Developer Guide

## 1. pipeline.yaml field reference

Every tool block in `pipeline.yaml` is validated by Pydantic before anything
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
| `runtime` | `conda` \| `docker` | required | How the tool is executed |
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

## 2. Adding a new tool

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
