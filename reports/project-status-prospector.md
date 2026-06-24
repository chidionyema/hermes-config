# Prospector Project Status Report

This status report is generated from the structural knowledge graph representation and analysis stored under `graphify-out/` in the Prospector codebase. 

- **Analysis Source File**: [graphify-out/.graphify_analysis.json](file:///Users/chidionyema/Documents/code/prospector/graphify-out/.graphify_analysis.json)
- **Graph Source File**: [graphify-out/graph.json](file:///Users/chidionyema/Documents/code/prospector/graphify-out/graph.json)
- **Built at Commit**: `aaa23c029ccc4fe5cf0b0554339ca00d850b69d6`

---

## 1. System Health & Graph Metrics

The knowledge graph maps the Prospector core engine, its test suites, specifications, and the storefront platform integration.

* **Total Nodes**: `3,285`
* **Total Edges/Links**: `7,112`
* **Hyperedges**: `0`
* **Average Community Cohesion**: `0.4109` (Minimum: `0.0345`, Maximum: `1.0000`)
* **Highly Coupled/Low-Cohesion Communities**: Out of `216` detected structural communities, `79` have a cohesion metric `< 0.20`, representing potential boundary violations or cross-cutting concerns that increase system complexity.

---

## 2. Key Components & Architecture

The system spans four main sub-systems representing different layers of execution:

### A. Python Prospector Engine (`prospector/` directory)
* **Core Runner**: [prospector/run.py](file:///Users/chidionyema/Documents/code/prospector/prospector/run.py) handles orchestration and CLI invocation (represented by 58 nodes in the graph).
* **Operators & Decisions**: [prospector/operator.py](file:///Users/chidionyema/Documents/code/prospector/prospector/operator.py) manages logic for executing checking rules against dossiers (71 nodes).
* **Retrieval Infrastructure**: [prospector/retrieval.py](file:///Users/chidionyema/Documents/code/prospector/prospector/retrieval.py) runs search operations and data-gathering tasks (65 nodes).
* **SQLite Persistence Index**: [prospector/store.py](file:///Users/chidionyema/Documents/code/prospector/prospector/store.py) manages a unified schema where all evaluation decisions are saved as JSON files and indexed inside a SQLite DB (`PRAGMA journal_mode=WAL` is configured in [prospector/store.py:L77](file:///Users/chidionyema/Documents/code/prospector/prospector/store.py#L77)).
* **Publishing Bridge**: [prospector/bridge.py](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py) packages packages, provisions products, uploads artifacts, and syncs the catalog (57 nodes).

### B. Store Platform Backend (`store_platform/src/Store.Api` & `Store.Catalog`)
* **ASP.NET Core Web API**: [store_platform/src/Store.Api/Program.cs](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Api/Program.cs) serves backend endpoints and handles catalog mutations.
* **Contracts**: [store_platform/src/Store.Api/Contracts/PublishRequest.cs](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Api/Contracts/PublishRequest.cs) defines the schema transfer contracts between the Python publishing bridge and C# storefront backend.

### C. Store Platform Frontend (`store_platform/src/Store.Web`)
* **Svelte/React/TypeScript Site**: The storefront catalog, which queries the C# API to display available, moat-verified packages to prospective buyers. Key API contract shapes reside in [store_platform/src/Store.Web/src/lib/api/types.ts](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web/src/lib/api/types.ts) (58 nodes).

### D. Specifications & Decisions
* Located in `docs/` and `specs/` (e.g. [docs/SYSTEM_SPECIFICATION.md](file:///Users/chidionyema/Documents/code/prospector/docs/SYSTEM_SPECIFICATION.md)), they specify design mandates such as multi-lane catalogues and payment rail abstraction.

---

## 3. External Dependencies & Boundaries

The system communicates with several key external interfaces, mapped directly to specific conceptual and code nodes:

* **Payment APIs**: Stripe and Paddle. The engine provisions items through [PaddleClient](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L602-L639) and [StripeProvisioner](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L640-L687).
* **AI & LLM Services**: Claude and Gemini verification engines (the primary "Moat Verification Engines"), along with non-critical chains (DeepSeek, MiniMax, Gemini-Flash) for generation variety.
* **Storage Systems**: Cloudflare R2 (S3-compatible) deliverable hosting. Executed via Python `boto3` in [R2Uploader](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L528-L590).
* **Framework Runtimes**: .NET 9.0 (`net9.0`) for storefront backend APIs, Svelte/React Node runtime environment for the UI.

---

## 4. End-to-End Data & Integration Flow

The integration pipeline connects candidate checking directly to storefront updates:

```
[Candidate Verification] 
       │ (Six Grounded Checks in operator.py)
       ▼
[Product Provisioning]
       │ (Stripe/Paddle Product + Price creation via bridge.py)
       ▼
[Artifact Packaging]
       │ (ZIP bundling in bridge.py)
       ▼
[Cloudflare R2 Upload]
       │ (R2Uploader in bridge.py publishes payload ZIP)
       ▼
[Store Catalog Sync]
       │ (POST /internal/catalog to Store.Api with X-Internal-Key)
       ▼
[Storefront Display]
       │ (Store.Web queries listed packs from Store.Api)
```

1. **Verify candidate**: The runner evaluates the candidate against six checks: Pain Reality, Value Durability, Incumbency, Payer Solvency, Distribution, and Legality.
2. **Authorize entitlement**: Prior to publishing, `EngineBridge.publish_pass` performs authorization checks by querying `POST /entitlements` on `Store.Api` ([store_platform/src/Store.Api/Program.cs:L312](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Api/Program.cs#L312)).
3. **Provision product and price**: `EngineBridge` invokes [StripeProvisioner](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L640) or [PaddleClient](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L602) to register products and pricing options.
4. **Create bundle**: `EngineBridge._create_bundle` builds a content-addressed ZIP package ([prospector/bridge.py:L420](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L420)).
5. **Upload deliverable**: `R2Uploader.upload` pushes the zip file to Cloudflare R2 ([prospector/bridge.py:L572](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L572)).
6. **Update store catalog**: `EngineBridge._update_catalog` issues a secure `POST /internal/catalog` call containing cryptographic headers (`X-Internal-Key`), pricing data (`pricePence`), and dossier summaries ([prospector/bridge.py:L471](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py#L471)).
7. **Persist catalog listing**: `Store.Api` verifies the secret, retrieves or initializes the `Pack` entity, populates marketing copy, and sets `IsListed = true` only if `ContentKey` is valid ([store_platform/src/Store.Api/Program.cs:L299](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Api/Program.cs#L299)).

---

## 5. Structural Warnings & Analysis Insights

The Graphify analysis identifies critical structural patterns and anomalies in the dependency topology:

### A. God Objects (Highest Degree Centrality)
These components are highly coupled to the rest of the codebase, meaning modifications to them carry a high risk (broad blast radius):
1. **Candidate** (`prospector_models_candidate`): Degree **168**. Root entity for all check evaluations.
2. **Config** (`prospector_config_config`): Degree **130**. Monolithic settings structure.
3. **load_config()** (`prospector_config_load_config`): Degree **110**. Central configuration entrypoint.
4. **Operator** (`prospector_operator_operator`): Degree **105**. Execution unit for checking logic.
5. **ProviderExhaustedError** (`prospector_errors_providerexhaustederror`): Degree **89**. Core fallback exception.
6. **Dossier** (`prospector_models_dossier`): Degree **89**. Container for evaluation artifacts.

### B. High-Risk Low-Cohesion Communities
* **Community 0** (Publish/Bridge pipeline, Cohesion = `0.0439`): Tightly couples the Python bridge client ([prospector/bridge.py](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py)) to deployment specs and external modules. This indicates that publishing concerns are scattered rather than isolated.
* **Community 1** (Core Operator/Orchestration, Cohesion = `0.0431`): Tightly couples execution logic with documentation (`HANDOVER.md`, `WORKFLOW.md`).
* **Community 7** (Store API Types, Cohesion = `0.0345`): Serves as a global dependency representing API shapes ([store_platform/src/Store.Web/src/lib/api/types.ts](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Web/src/lib/api/types.ts)). Any contract change here triggers wide UI re-compilation.

### C. Surprise Crossings (Cross-Namespace Connections)
* **Conceptual-to-Code Mapping**: `Payment Rail Independence Spec` connects to C# backend [FulfilmentService](file:///Users/chidionyema/Documents/code/prospector/store_platform/src/Store.Api/Services/FulfilmentService.cs) via `conceptually_related_to`, bridging document definitions with active service implementations.
* **Test Utility Leakage**: `FakeClock` in unit tests has an inferred connection directly to core [CircuitBreaker](file:///Users/chidionyema/Documents/code/prospector/prospector/breaker.py), indicating a tight dependency between unit testing strategies and operational safety components.
* **Auxiliary Utility Coupling**: `_CapturingGenOp` and `ScoreResult` utilities from test tools are linked directly to [EngineBridge](file:///Users/chidionyema/Documents/code/prospector/prospector/bridge.py) code.
