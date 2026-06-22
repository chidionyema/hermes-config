# Prospector Knowledge Graph Status Report

## Executive Summary
This report provides a status summary of the Prospector project as extracted and analyzed from its `graphify-out` knowledge graph. The knowledge graph represents the structural relationships, code entities, rationales, documentation files, and dependencies of the Prospector codebase.

## Metadata & Generation Info
- **Source Artifacts**: `graphify-out/graph.json`, `graphify-out/.graphify_analysis.json`, `graphify-out/.graphify_semantic_marker`
- **Build Commit Target**: `aaa23c029ccc4fe5cf0b0554339ca00d850b69d6`
- **Token Analysis Metrics**:
  - Input tokens analyzed: **125,477**
  - Output tokens generated: **33,314**

---

## 1. Network Topography Statistics
A summary of the node and edge distribution within the knowledge graph.

### Node Distribution by Type
| Entity Type | Description | Count | Percentage |
|---|---|---|---|
| **code** | Source code entities (classes, methods, functions, files) | 2,476 | 75.4% |
| **rationale** | LLM-generated decision rationales, audit details | 737 | 22.4% |
| **document** | Specification files, Markdown documentation, user stories | 41 | 1.2% |
| **concept** | Core system definitions and abstract concepts | 26 | 0.8% |
| **image** | Project diagram assets and visuals | 5 | 0.2% |
| **Total** | | **3,285** | **100%** |

### Node Extraction Source Origin
- **ast (Abstract Syntax Tree)**: 3,181 nodes
- **Manual/Document Extraction (None)**: 104 nodes

### Link Relations
The graph contains **7,112** total relationships. Below are the counts of relationship categories:
- `calls`: 1,638
- `contains`: 1,323
- `uses`: 846
- `references`: 757
- `rationale_for`: 735
- `imports`: 712
- `method`: 493
- `imports_from`: 416
- `re_exports`: 77
- `inherits`: 51
- `implements`: 19
- `conceptually_related_to`: 18
- `defines`: 17
- Other relations (e.g., `specifies`, `enforces`, `optimizes`, `hardens`, etc.): 10

---

## 2. Key Architectural Entities ("God" Nodes)
These nodes represent the most heavily integrated/connected components in the graph based on node degree.

| Node Name | Node Identifier | Degree | Architectural Role |
|---|---|---|---|
| **Candidate** | `prospector_models_candidate` | 168 | Primary domain model representing investment candidates. |
| **Config** | `prospector_config_config` | 130 | Configuration loader and system property parser. |
| **load_config()** | `prospector_config_load_config` | 110 | Configuration setup routine. |
| **Operator** | `prospector_operator_operator` | 105 | Central processing class for orchestrating model invocations. |
| **ProviderExhaustedError** | `prospector_errors_providerexhaustederror` | 89 | Central error mechanism handling API exhaustion across LLM providers. |
| **Dossier** | `prospector_models_dossier` | 89 | Encapsulates the output check history and evaluation of a Candidate. |
| **Store** | `prospector_store_store` | 88 | Database and persistence layers abstraction. |
| **Decision** | `prospector_models_decision` | 87 | The final verdict representation structure. |
| **MockOperator** | `prospector_operator_mockoperator` | 81 | Essential mock implementation for test suite verification. |
| **CheckResult** | `prospector_models_checkresult` | 77 | Stores findings/verdicts from specific gate execution checks. |

---

## 3. Community Detection & Cohesion
- **Total Communities**: 216 distinct communities detected.
- **Top Communities by Node Count**:
  - **Community 0** (89 nodes): Main system runtime modules & utilities.
  - **Community 1** (82 nodes): Telemetry, operators, runtime errors.
  - **Community 2** (78 nodes): Test suites, unit/behavioural tests, decay loop, golden runs.
  - **Community 3** (68 nodes): UI frontend components, component props, select components.
  - **Community 4** (64 nodes): API/Retrieval search providers, bravesearch, openrouter, exasearch.
- **Cohesion Metric**: Fully cohesive sub-graphs (e.g. Communities 173 to 182) exhibit a cohesion score of **1.0**, indicating highly decoupled subcomponents.

---

## 4. Inferred Relationships & Architectural Surprises
The graphify analyzer detected several unexpected/inferred dependencies that cross typical layer boundaries:

1. **Document-to-Code Mapping**:
   - **Source**: `Payment Rail Independence Spec`
   - **Target**: `FulfilmentService (provider-agnostic)`
   - **Files**: `docs/PAYMENT_RAIL_INDEPENDENCE_SPEC.md` and `store_platform/src/Store.Api/Services/FulfilmentService.cs`
   - **Reason**: The C# fulfillment service implicitly aligns with the payment rail decoupling spec despite no direct semantic imports.
2. **Cross-Community Testing Dependency**:
   - **Source**: `FakeClock`
   - **Target**: `CircuitBreaker`
   - **Files**: `tests/unit/test_breaker.py` and `prospector/breaker.py`
   - **Reason**: Integrates clock mocking across community boundaries to verify timing-dependent circuit breaking.
3. **Bridge-to-Tool dependencies**:
   - **Sources**: `_CapturingGenOp`, `ScoreResult`
   - **Target**: `EngineBridge`
   - **Files**: `tools/prove_diversity.py` and `prospector/bridge.py`
   - **Reason**: Test and verification tooling dependency on the main engine execution bridge.
4. **Behavioural Validation Constraints**:
   - **Source**: `MockGenOp`
   - **Target**: `Thresholds`
   - **Files**: `tests/behavioural/test_gen_quality_e2e.py` and `prospector/config.py`
   - **Reason**: Verification checks use configured quality limits/thresholds directly.
