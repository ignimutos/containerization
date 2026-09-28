---
name: image-readme
description: Use when asked to generate or refresh README files for one image or every image under images/ in this repository.
---

# image-readme

## Overview
Generate repo-local image READMEs from the checked-in image definition plus official upstream sources. This skill updates `images/<name>/README.md` directly and is independent from CI or any automated sync workflow.

## Modes
- **Single-image mode:** update exactly one `images/<name>/README.md`
- **All-images mode:** update every `images/*/README.md` in this repository

## Required workflow
For each target image, follow this order:

1. **Read local sources first**
   - `images/<name>/Dockerfile`
   - `images/<name>/config.yml`
   - `images/<name>/misc/**`
   - existing `images/<name>/README.md` if present
2. **Identify the primary official upstream source**
   - Prefer repos declared in `config.yml` (`github_tag`, `github_sha`, related repos)
   - Otherwise infer from `Dockerfile` (`FROM`, `git clone`, downloaded artifacts)
   - Use the existing README only as a clue, not as authority
3. **Fetch upstream material**
   - **Required:** use Firecrawl for official docs, official repo README pages, release pages, or configuration references
   - **When applicable:** use Context7 for library/CLI/framework docs that help explain configuration or runtime usage accurately
4. **Write the README**
   - Focus on how to use this container image
   - Overwrite `images/<name>/README.md` directly
   - Do not ask for confirmation before overwriting

## Stable output structure
Use the same top-level structure for every image, in this exact order:

```markdown
# <Image name>

> One-sentence summary of the container image.

## Upstream Project
## What This Image Adds
## Image Targets
## Configuration
## Files, Ports, and Volumes
## Usage
## Notes
```

Rules:
- Keep all top-level headings in the same order for every image
- If a section has nothing meaningful to list, write `Not applicable.` instead of removing the heading
- `Image Targets` must describe build targets or variants when present; otherwise say the image has a single runtime target
- `Configuration` should prioritize environment variables, mounted files, and values inferred from local scripts/config
- `Usage` should show concise container-oriented examples only when they are supported by local files and upstream docs

## Content priorities
Prioritize facts in this order:
1. Local checked-in image files for container behavior
2. Official upstream docs/repo content fetched with Firecrawl
3. Context7 references when they improve accuracy for config/runtime details

Keep the README centered on:
- what software the image packages
- what this repository changes or adds
- how to configure and run the image
- important ports, volumes, scripts, and caveats

Do **not** turn the README into a full upstream manual. Summarize only the upstream details needed to use the container image correctly.

## Guardrails
- README generation is an authoring task, not a CI task
- Do not modify CI, workflow, or build code while using this skill
- Do not create sidecar draft files; write the final content straight to `images/<name>/README.md`
- Do not write README files outside `images/*/README.md`
- Keep terminology and section order consistent across all images
- Preserve only facts that still match current local image files and current upstream docs

## Quick reference
- One image: inspect one image directory, research upstream, overwrite one README
- All images: iterate all image directories, apply the same structure, overwrite every README in place
- Missing upstream clarity: inspect `config.yml` first, then `Dockerfile`, then existing README links, then validate with Firecrawl
- Context7 use: only when it adds authoritative product/tool documentation relevant to end-user usage
