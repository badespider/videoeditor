# Project Tasks

## Metadata

- **Last Updated**: Wednesday, December 10, 2025 at 10:28:15 AM
- **Total Tasks**: 7
- **Status Breakdown**:
  - 📋 todo: 7
- **Priority Breakdown**:
  - 🟠 high: 1
  - 🟡 medium: 6

## Overview

### Overall Progress: 0%

`░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░` 0/7 tasks complete

### Status Breakdown

📝 **backlog**: `░░░░░░░░░░░░░░░` 0 tasks (0%)
📋 **todo**: `███████████████` 7 tasks (100%)
⚙️ **in_progress**: `░░░░░░░░░░░░░░░` 0 tasks (0%)
👁️ **review**: `░░░░░░░░░░░░░░░` 0 tasks (0%)
✅ **done**: `░░░░░░░░░░░░░░░` 0 tasks (0%)
🚫 **blocked**: `░░░░░░░░░░░░░░░` 0 tasks (0%)

## 📋 To Do

### 🟠 Set up New Project (task-1765380481876-setup)

**Priority:** high | **Complexity:** ★★★☆☆ (3/10) | **Created:** 12/10/2025

Tags: `setup` `initialization`

> Initial setup and configuration for the New Project project.

> Automatically created when adding first task

**Notes:**
- 💬 **comment** (12/10/2025, 10:28:01 AM, System): Project initialized on 12/10/2025

---

### 🟡 Character Extraction Upgrade - AI-Based Extraction (task-1765380481998-0c1y3)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Implement the core CharacterExtractor service with Gemini-powered extraction. Create CharacterInfo data model and extract_characters_ai() method that analyzes transcripts to identify characters with names, aliases, descriptions, roles, and visual traits. This replaces the basic regex-based extraction in ScriptGenerator._extract_names_from_dialogue().

---

### 🟡 Character Extraction Upgrade - Visual Tracking Integration (task-1765380484596-wzp05)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Integrate with Memories.ai Chat API for visual character identification. Implement extract_characters_visual() to leverage video understanding for face tracking, appearance detection, and visual descriptions. This provides higher accuracy than text-only extraction.

---

### 🟡 Character Extraction Upgrade - Merge Engine & Deduplication (task-1765380487291-vs0v0)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Build character merge engine to combine results from AI extraction, visual tracking, and existing character database. Implement fuzzy name matching, alias resolution, and confidence scoring to prevent duplicate characters.

---

### 🟡 Character Extraction Upgrade - Persistent Database (task-1765380490345-9ilrw)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Implement CharacterDatabase class for persistent character storage across episodes. Use Redis for Phase 1 (with PostgreSQL migration path). Store series-level character profiles, speaker mappings, and cross-episode tracking.

---

### 🟡 Character Extraction Upgrade - Pipeline Integration (task-1765380493370-nepub)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Integrate CharacterExtractor into the video processing pipeline. Add character extraction step after video upload, build character guide for narration, and save results to database. Update job_data to include series_id for multi-episode tracking.

---

### 🟡 Character Extraction Upgrade - API & UI (Optional) (task-1765380495578-eofmg)

**Priority:** medium | **Complexity:** ★★★★★ (5/10) | **Created:** 12/10/2025 | **Updated:** 12/10/2025

> Create REST API endpoints for character management (GET/POST/PUT/DELETE). Optional frontend UI for viewing, editing, and correcting character identifications. Enables manual override of AI mistakes.

---

