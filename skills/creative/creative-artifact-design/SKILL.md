---
name: creative-artifact-design
description: "Create visual and generative artifacts across diagrams, ASCII/video, HTML prototypes, infographics, animation, sketches, and design-token systems."
version: 1.0.0
author: Hermes Agent
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [creative, visual, diagrams, ascii, html, infographic, animation, p5js, design]
---

# Creative Artifact Design

Use this umbrella for visual deliverables whose implementation may be SVG, HTML/CSS, canvas, ASCII, animation, or a structured diagram.

## Choose the medium
- **Architecture and flow**: SVG/HTML or Excalidraw-style JSON; preserve legible hierarchy and directional semantics.
- **Text-native visuals**: ASCII art/video and terminal compositions; test monospace width and frame rate.
- **Web prototypes**: single-file HTML by default; use deliberate layout, responsive behavior, and real interaction rather than a static mock.
- **Infographics and design systems**: establish audience, data hierarchy, tokens, and export constraints before styling.
- **Generative/animated work**: p5.js, Manim, or equivalent; make the render reproducible and verify output files.

## Shared workflow
1. Clarify audience, output format, dimensions, and delivery path.
2. Pick the smallest tool that satisfies the medium.
3. Build a representative composition before polishing.
4. Render/export and inspect the actual artifact, not only source.
5. Iterate on hierarchy, contrast, spacing, and readability.

## Quality gates
- Text remains readable at the requested size.
- Visual hierarchy communicates the intended story without narration.
- External assets and fonts have a fallback or are bundled.
- Generated files open successfully and are placed where requested.

## Tool-specific subsections
- Diagram JSON must remain valid and retain stable IDs.
- ASCII output must account for Unicode display width.
- HTML artifacts should be self-contained unless dependencies are explicitly requested.
- Animation work needs a deterministic seed or documented render parameters.
