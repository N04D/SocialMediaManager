# Agentic Content Graph v0.1

SocialMediaManager is an open-source agentic distribution framework. Core owns generic primitives; plugins own domain behavior. A new niche should be possible with plugins, playbooks, entities, outcomes, and policies, without redesigning core.

## Core Concepts

- Entity: a typed thing the system can reason about, such as article, video, product, job, release, event, offer, or course. Core stores id, entity type, source plugin, external reference, title, timestamps, and plugin-validated metadata.
- Source: the origin context for content. Content items have a primary source identity separate from their canonical text.
- Primary source: primary source type, entity id, reference, and metadata. Legacy written drafts map to written without rewriting files.
- Canonical representation: uniform AI input with canonical text, media references, canonical metadata, and provenance. A transcript edit preserves the original transcript and marks the canonical transcript as edited.
- Asset: concrete text/media content. Media assets continue to use the existing media framework; graph assets reference media IDs instead of creating separate storage.
- Transformation: plugin capability that declares accepted and produced capability identifiers, configuration, provenance, and execution evidence. Core orchestrates; plugins implement.
- Relationship graph: durable from entity, relationship type, to entity, metadata, and provenance. Relationship types are extensible.
- Intent: generic identity and constraints such as grow audience, sell product, book meetings, or recruit.
- Campaign: connects source entities, intent, selected plugins, transformations, variants, publications, outcomes, and metadata.
- Outcome: generic result such as view, click, lead, meeting, signup, cart, purchase, revenue, application, or registration. Unknown states remain explicit: not_configured, not_collected, provider_pending, not_observed, and unsupported are not zero.
- Playbook: contract for name, intent, required capabilities, optional capabilities, workflow stages, policies, and success metrics. There is no marketplace in v0.1.
- Policy: declarative rules such as never publish without confirmation, never invent discounts, only promote in-stock products, or require approved accounts. Executable policy payloads are forbidden.

## Plugin Families

Capability prefixes map plugins into Sources, Transformations, Media, Channels, Commerce, Providers, Analytics, Actions, Content, and Publication. The registry can answer which plugins provide transcript, produce short video, publish to a channel, expose product catalog, or provide sales outcomes.

Channel configuration belongs under Plugins -> Channels -> the channel plugin. LinkedIn owns account, connection, formatting defaults, CTA behavior, media defaults, scheduling defaults, provider/browser selection, and channel policy. Composer only carries per-content overrides.

Commerce configuration belongs under Plugins -> Commerce -> the commerce plugin. Shopify or WooCommerce can later provide entity.product, entity.collection, commerce.product_catalog, outcome.product_click, and outcome.sale without commerce logic in core.

## Attribution Chain

Primary source -> canonical representation -> transformation -> variant -> publication -> outcome.

Revisions snapshot primary source identity, canonical representation identity, source provenance, and relationship IDs. Variants keep the revision, primary source, optional campaign/intent, and optional transformation run.

## Long-form Video to Clips

The architecture is modular: source video -> transcript/timeline -> candidate segments -> selected clips -> rendered short assets.

The v0.1 proof is deterministic and transcript-only. It scores timestamped timeline segments and can return a synthetic short asset contract when a synthetic video reference exists. Future plugins can consume audio energy, speaker changes, scene changes, face detection, visual subjects, silences, or semantic topics without core changes.

## Examples

YouTube creator: YouTube source -> pasted transcript provenance -> deterministic clip candidate -> LinkedIn variant.

E-commerce creator: Article source -> product entity relationship -> commerce CTA variant -> click/sale outcome contract.

LinkedIn lead generation: LinkedIn content -> lead outcome -> booked_meeting intent/playbook contract.

Developer release: Release entity -> changelog/social transformation -> channel variant -> signups outcome.

For Shopify stores, recruitment, podcasts, real estate, course creators, and LinkedIn appointment funnels, the intended answer is: no core redesign; add plugins, playbooks, entity/outcome contracts, and policies.
