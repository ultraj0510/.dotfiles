---
name: gpt-image-2-style-library
description: Choose GPT-Image2 / gpt-image-2 visual styles and industrial prompt templates from the awesome-gpt-image-2 style library. Use when an agent needs to create, rewrite, classify, or improve image-generation prompts with repository-backed templates, categories, style tags, scene tags, pitfalls, and example cases.
---

# GPT-Image2 Style Library

Use this skill to turn a user's image-generation intent into a production-ready GPT-Image2 prompt using the awesome-gpt-image-2 style library.

## Example Output

![City life system map example](assets/city-life-system-map.png)

Example request: `用 gpt-image-2-style-library 技能生成城市生命系统图谱`

## Reference

- Read `references/style-library.md` before choosing a template or style.
- The reference is generated from `data/style-library.json` in the repository.
- Prefer the reference over memory when template names, categories, covers, or style tags matter.

## Workflow

1. Detect the user's language and answer in that language.
2. Identify the user's target output: product, poster, UI, infographic, brand, photo, illustration, character, scene, history, document, or special task.
3. Match the request in this order: template category, visual style tag, scene tag, then nearest example cases.
4. If one template is clearly strongest, use it directly. If several are plausible, choose the best fit from the user’s intent and briefly state the choice. Present options when the user requests exploration; ask only when a missing preference materially changes the requested outcome and cannot reasonably be inferred.
5. Build the final prompt with these blocks:
   - subject and task
   - composition and layout
   - visual style and materials
   - text and label requirements
   - aspect ratio and output format
   - constraints and negative details
6. Include the selected template name and any useful example case IDs.

## Output Defaults

- For prompt-writing requests, provide a copyable prompt. For image-generation requests, use the prompt with the available image-generation tool and deliver the image; do not stop at the prompt or ask for permission already implied by the generation request. Follow the image tool’s required input and capability boundaries.
- If generation is unavailable, clearly label the prompt as a partial deliverable, not a generated image.
- Keep constraints concrete: exact text, aspect ratio, readable labels, layout hierarchy, and avoided artifacts.
- For Chinese requests, write the final prompt in Chinese unless the user asks for English.
- For English requests, write the final prompt in English unless the user asks for Chinese.
- When the user asks for multiple concepts, reuse one template and vary subject, composition, palette, and scene.

## Maintenance

When the source repository changes, run:

```bash
npm run generate:style-skill
```

To install the skill into the local Codex skill folder, run:

```bash
npm run install:skill
```
