# Haworks Platform Project Status Report

**Generated on:** 2026-06-24  
**Source Knowledge Graph:** [GRAPH_REPORT.md](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md) (Extraction dated 2026-06-21)  
**Target Project:** Haworks Platform (Microservices-based .NET 9 backend & Python AI service)

---

## 📊 1. Core Graph Metrics
According to the codebase knowledge graph summary ([GRAPH_REPORT.md:L6-9](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L6-L9)):
* **Total Nodes:** 14,922
* **Total Edges:** 22,657
* **Total Communities:** 1,527 (1,295 analyzed/shown, 232 thin communities omitted)
* **Extraction Quality:**
  * **Extracted Edges:** 99%
  * **Inferred Edges:** 1% (273 edges, average confidence: 0.57)
  * **Ambiguous Edges:** 0%

---

## 🏛️ 2. Core Abstractions & Dependency Hubs ("God Nodes")
The top 10 most connected nodes (hubs) in the Haworks Platform codebase represent either central testing components, shared utilities, or key interface boundary points ([GRAPH_REPORT.md:L1329-1340](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1329-L1340)):

| Rank | Node Name | Edges Count | Architecture Role / Significance |
| :--- | :--- | :--- | :--- |
| 1 | `PlatformGuardTests` | 137 | Central suite verifying architecture and guard rails. |
| 2 | `Fact` | 120 | xUnit base assertion decorator; indicates high test coverage density. |
| 3 | `Haworks.BuildingBlocks` | 83 | Core shared library for common patterns, logging, health, and extensions. |
| 4 | `Haworks.BuildingBlocks.Testing` | 66 | Core shared integration testing fixtures and helpers. |
| 5 | `Haworks.Contracts` | 47 | Shared contract types/DTOs for cross-service asynchronous event communication. |
| 6 | `DemoController` | 44 | Endpoint playground demonstrating fault-injection, circuit breakers, etc. |
| 7 | `Payments Service` | 39 | Central payment service interface / integration boundary. |
| 8 | `Settings` | 38 | Unified application configuration structures. |
| 9 | `AuditableEntity` | 38 | Entity base type representing state tracking for the Audit microservice. |
| 10 | `VaultServiceTests` | 34 | Test harness ensuring secret management integrity. |

---

## 🔗 3. Surprising & Inferred Cross-Service Dependencies
Several key relationships were inferred between documentation, READMEs, specs, and source files across service boundaries ([GRAPH_REPORT.md:L1341-1352](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1341-L1352)):
1. **Contracts Library referencing Search Service (Inferred):**
   * Linkage: [src/Contracts/README.md](file:///Users/chidionyema/Documents/code/haworks-platform/src/Contracts/README.md) $\rightarrow$ `docs/agent-briefs/search-service-spec.md`
2. **Contracts Library referencing Catalog Service (Inferred):**
   * Linkage: [src/Contracts/README.md](file:///Users/chidionyema/Documents/code/haworks-platform/src/Contracts/README.md) $\rightarrow$ `docs/agent-briefs/search-service-spec.md`
3. **Architecture Analyzers referencing Catalog Service (Inferred):**
   * Linkage: `src/Analyzers/README.md` $\rightarrow$ `docs/agent-briefs/search-service-spec.md`
4. **Audit Service referencing S3 Object Storage (Extracted):**
   * Linkage: `docs/agent-briefs/audit/L0-skeleton.md` $\rightarrow$ [src/Media/README.md](file:///Users/chidionyema/Documents/code/haworks-platform/src/Media/README.md)
5. **Contracts Library referencing Payments Service (Inferred):**
   * Linkage: [src/Contracts/README.md](file:///Users/chidionyema/Documents/code/haworks-platform/src/Contracts/README.md) $\rightarrow$ `docs/agent-briefs/checkout/C1-subscription-endpoints.md`

---

## 🔄 4. Circular Import Issues (Technical Debt)
The knowledge graph flags circular dependencies in the AI service, which are candidates for refactoring ([GRAPH_REPORT.md:L1353-1356](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1353-L1356)):
* **1-file cycle (self-import/imports itself):**
  * `src/Ai/app/main.py -> src/Ai/app/main.py`
  * `src/Ai/app/services/recommendation_service.py -> src/Ai/app/services/recommendation_service.py`

---

## 🧩 5. Major Architectural Communities
The following list outlines key communities identified by the clustering algorithm, showing how microservices and architectural layers group together:

* **Community 2 (BFF Web Client API):** Covers `BffWeb.Api`, `BffWeb.Application`, `BffWeb.Architecture`, `BffWeb.Domain`, `BffWeb.Infrastructure`, `BffWeb.Integration`, `PricingRequestedConsumer`, and `PricingRequestedEvent` ([GRAPH_REPORT.md:L1367-1370](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1367-L1370)).
* **Community 4 (Catalog Microservice):** Clusters `Catalog.Api`, `Catalog.Application`, `Catalog.Architecture`, `StockReservedConsumerTests`, `Catalog.Domain`, `Catalog.Infrastructure`, `Catalog.Integration`, and `Catalog.Unit` ([GRAPH_REPORT.md:L1375-1378](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1375-L1378)).
* **Community 5 (Notifications Microservice):** Clusters `Notifications.Api`, `Notifications.Application`, `Notifications.Domain`, `Notifications.Infrastructure`, `Notifications.Integration`, `SendNotificationCommandValidatorTests`, `Notifications.Unit`, and `FirebaseAdmin` dependency ([GRAPH_REPORT.md:L1379-1382](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1379-L1382)).
* **Community 6 (Identity Microservice):** Focuses on authentication, registration/profile events, containing `Identity.Api`, `Identity.Application`, `Identity.Architecture`, `UserProfileChangedConsumerTests`, `Identity.Domain`, `User`, and `ExtractorRegistry` ([GRAPH_REPORT.md:L1383-1386](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1383-L1386)).
* **Community 7 & 8 (Chaos Testing & Fault Isolation):** Highlights resilience patterns, grouping `ChaosManager`, `FaultInjectionStrategy`, `IChaosStrategy`, `AsyncCircuitBreakerPolicy`, `CircuitRequest`, `IdempotencyRaceRequest`, and `DemoController` ([GRAPH_REPORT.md:L1387-1394](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1387-L1394)).
* **Community 11 (Orders Microservice):** Encapsulates the entire order processing pipeline: `Orders.Api`, `Orders.Application`, `Orders.Architecture`, `Orders.Domain`, `Orders.Infrastructure`, `Orders.Integration`, `OrderEventsConsumerTests`, and `EndToEndCaptureTests` ([GRAPH_REPORT.md:L1403-1406](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1403-L1406)).
* **Community 16 & 29 (Payments & Stripe Integration):** Separates core Payments Service (`Payments.Api`, `Payments.Application`, etc. in Community 29) from payment client handlers, Stripe webhook processors, and monolith port briefs in Community 16 ([GRAPH_REPORT.md:L1423-1426](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1423-L1426), [GRAPH_REPORT.md:L1475-1478](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1475-L1478)).
* **Community 34 (Checkout Orchestrator):** Manages saga processes: `CheckoutOrchestrator.Api`, `CheckoutOrchestrator.Application`, `CheckoutOrchestrator.Architecture`, `CheckoutOrchestrator.Domain`, `CheckoutOrchestrator.Infrastructure`, and related test suites ([GRAPH_REPORT.md:L1495-1498](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1495-L1498)).
* **Community 38 (Change Data Capture / CDC Spec):** Contains elements mapped to CDC implementation: `CDC Service Spec`, `Debezium CDC`, `Audit Service`, `BFF`, and `Catalog Service` ([GRAPH_REPORT.md:L1511-1514](file:///Users/chidionyema/Documents/code/haworks-platform/graphify-out/GRAPH_REPORT.md#L1511-L1514)).
