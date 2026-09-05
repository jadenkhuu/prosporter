---
title: ProSporter Phase 2 Project Schedule
source_file: ../../ProSporter sprint.pdf
source_created: 2026-08-27
converted_to_markdown: 2026-09-03
document_type: repository-scoped contractual extract
repository_scope: ProSporter ecommerce only
currency: AUD
---

# ProSporter Phase 2 Project Schedule

This is an LLM-friendly, ProSporter-only extraction of the Phase 2 obligations in [`ProSporter sprint.pdf`](../../ProSporter%20sprint.pdf). It includes shared agreement terms only when they affect the ProSporter ecommerce migration, storefront, launch, handover, warranty, hosting, or support.

The source PDF also describes separate marketing-site work. That work is intentionally excluded from this repository and this Markdown file. The PDF remains the authoritative contractual source if this scoped extraction and the source ever differ.

## Repository scope boundary

This repository is only for:

- The ProSporter ecommerce storefront.
- Migration from the existing WooCommerce/WordPress store to Shopify.
- The headless Next.js frontend.
- ProSporter catalog, content, customers, checkout, SEO, redirects, deployment, archive, handover, and support obligations.

This repository is not for any separate organisation, club, marketing website, CMS, sports-data feed, social feed, registration flow, or related deliverable described elsewhere in the source agreement.

## LLM quick reference

### Deliverable

A Shopify ecommerce storefront using a Next.js headless frontend, including migration from the existing WooCommerce/WordPress store and deployment to the existing ProSporter domain.

### Included work

- Frontend storefront design and build.
- Product listing, product detail, collection, cart, and checkout flows.
- Shopify theme/storefront configuration.
- WooCommerce/WordPress migration.
- DNS configuration and deployment.
- Performance, quality, security, SEO, analytics, form, browser, and responsive testing.
- Migration reconciliation and historical-order archive.
- Handover and a 30-day warranty.

### Migration rule

Historical orders are not imported into Shopify. They are delivered as a complete, readable archive containing orders, payments, refunds, fulfilments, and applicable attachments.

### Timing

- Kickoff: agreement signed and required access/materials received.
- Storefront and migration delivered for review: 10 business days from Kickoff.
- Review Period: 7 days from delivery.
- Live deployment and handover: 3 business days from written acceptance.

### ProSporter milestone amounts

- Phase 2 acceptance: $250.
- Phase 2 live delivery and handover: $250.
- Combined ProSporter milestone value: $500.

The source agreement's total project fee also covers work outside this repository and must not be interpreted as the ProSporter-only budget.

## 1. Acceptance criteria

The ProSporter site is accepted when it meets the following criteria, verified before handover for review.

| # | Criterion | Standard |
| ---: | --- | --- |
| 1 | Responsive layout | Renders without horizontal scroll or broken layout at 375px, 768px, and 1280px widths |
| 2 | Browsers | Current stable Chrome, Safari, Firefox, and Edge |
| 3 | Forms | All forms submit successfully and deliver to the client-nominated email address; validation and error states work |
| 4 | General performance | Lighthouse Performance score of 85 or above on mobile for the home page and one representative interior page |
| 5 | Security | HTTPS enforced site-wide with a valid certificate; no credentials or secrets exposed in client-side code |
| 6 | Basic SEO | Unique title and meta description per page; semantic heading structure; `sitemap.xml`; `robots.txt`; Open Graph tags |
| 7 | Analytics | Google Analytics 4, or a client-nominated equivalent, installed and recording on a client-owned property |
| 8 | Links | All internal links resolve; no broken links on any page |
| 9 | Errors | No JavaScript console errors on any key page |
| 10 | Testing | Functional test pass completed before deployment, with results shared with the client |

## 2. ProSporter scope of work

- Frontend storefront design and build.
- Product listing, product detail, collection, cart, and checkout flows.
- Shopify theme/storefront configuration.
- Migration from the existing WooCommerce/WordPress store as defined in section 4.
- DNS configuration and deployment to the existing ProSporter domain.
- All acceptance criteria in section 1.
- The additional performance and quality standard in section 3.

## 3. Performance and quality standard

ProSporter must operate at the standard reasonably expected of a modern Australian online store: fast loading, smooth and responsive browsing, and reliable cart and checkout.

| # | Criterion | Standard |
| ---: | --- | --- |
| 1 | Loading speed | Lighthouse Performance score of 85 or above on mobile for the home page, a collection page, and a product detail page; Largest Contentful Paint under 2.5 seconds on each |
| 2 | Responsive browsing | Cumulative Layout Shift below 0.1 and Interaction to Next Paint under 200 milliseconds across navigation, search, filtering, and product browsing |
| 3 | Cart and checkout | Add to cart, cart update, discount-code entry, shipping calculation, payment, and order confirmation complete reliably; verified by an end-to-end test order through live checkout |
| 4 | Critical Defects | No unresolved Critical Defect at go-live |

A Critical Defect is a fault that:

- Prevents a customer from browsing products.
- Prevents adding an item to the cart.
- Prevents checkout or order confirmation.
- Causes incorrect pricing or stock levels.
- Causes loss of order data.

The implementation must be verified before review, and the results must be shared with the client. Failures within the implementation or configuration must be remedied at no additional cost before acceptance and during the Warranty Period.

The standard applies to the store as built and configured by the service provider. It excludes the performance of Shopify itself, Shopify-hosted checkout, client-requested third-party apps, oversized media added after acceptance, and a customer's device or network connection.

## 4. WooCommerce to Shopify migration scope

| Item | Included | Notes |
| --- | :---: | --- |
| Products | Yes | Titles, descriptions, pricing, and SKUs |
| Product variants | Yes | Options, variant pricing, and variant SKUs |
| Product images | Yes | Migrated and reattached to the correct product and variant |
| Stock levels | Yes | Point-in-time snapshot taken at cutover |
| Collections/categories | Yes | Mapped to Shopify collections |
| Pages | Yes | Static content pages |
| Blog posts | Yes | Posts and their images |
| SEO data | Yes | Page titles and meta descriptions carried across |
| URL redirects | Yes | 301 map from old to new product, collection, page, and post URLs |
| Discount codes | Yes | Active codes recreated; expired and historical codes excluded |
| Shipping settings | Yes | Zones and rates recreated to match the current store |
| Tax settings | Yes | Configured to match the current store |
| Payment settings | Yes | Shopify Payments and any client-nominated gateway configured and tested; account verification and merchant agreements remain the client's responsibility |
| Customer records | Yes | Customers migrated without passwords; the customer transition depends on the selected Shopify account mode |
| Historical orders | No | Not imported into Shopify; delivered as the archive in section 5 |

## 5. Historical-order archive

The complete order history through the cutover date must be delivered outside Shopify as readable CSV files.

### Required data

- Orders: order number, date, status, customer/contact details, billing and shipping addresses, line items, SKU, quantity, price, discounts, shipping, tax, and total.
- Payments: payment method, transaction reference, amount, currency, payment date, and payment status.
- Refunds: amount, date, reason where recorded, source order, and refunded line items.
- Fulfilments: status, date, carrier, tracking number where recorded, and fulfilled items.
- Attachments: invoice, packing-slip, and equivalent source files where present.

### Format and verification

- CSV files must open in Excel, Google Sheets, or another spreadsheet tool without requiring WordPress, WooCommerce, Shopify, or a service-provider system.
- The archive must reconcile to the source store's complete order count.
- Archive discrepancies raised during review or warranty must be corrected at no additional cost.
- The archive is part of the final handover.

## 6. Migration reconciliation

Before go-live, provide source-to-destination counts for:

- Products.
- Variants.
- Images.
- Collections.
- Pages.
- Blog posts.

Investigate and resolve every unexplained discrepancy before the store goes live.

## 7. Customer migration and account transition

- Customer records are personal information and may be used only for this migration.
- Customer passwords cannot be transferred from WooCommerce to Shopify.
- The original Schedule describes imported customers as deactivated accounts that receive invitations before setting a new password.
- Current Shopify customer accounts may instead use passwordless email verification. The selected account mode and customer communication must be approved in writing before implementation.
- No invitation or transition email may be sent before the client approves its timing and wording in writing.
- Working copies of customer data must not be retained beyond the applicable contractual retention period.
- Security incidents affecting client data are subject to the agreement's notification obligations.

## 8. Out of scope

- Content writing and copywriting.
- Photography, videography, and custom illustration.
- Logo design or brand-identity development.
- Ongoing SEO, keyword research, link building, or content marketing.
- Paid advertising setup or management.
- Custom integrations beyond those expressly included, such as ERP, CRM, accounting, or fulfilment systems.
- Importing historical orders into Shopify.
- Multi-language or multi-currency configuration.
- Native mobile applications.
- Email-marketing platform setup, template design, or list migration.
- Third-party app configuration beyond initial installation.
- WCAG AA or higher certification beyond the semantic structure in the acceptance criteria.

No additional work or cost is authorized without the client's prior written approval under the agreement's variation process.

## 9. Client inputs and dependencies

The client provides:

- Brand assets, colour/type specifications, and applicable guidelines.
- Existing copy, product descriptions, page content, photography, and imagery.
- Access to the WooCommerce/WordPress store, domain/DNS, Shopify account, analytics property, and payment accounts.
- Timely feedback and written approvals at each review point.

The service provider provides:

- ProSporter design, layout, and storefront implementation.
- Properly licensed stock imagery and fonts where required.
- Migration, deployment, DNS configuration, and testing.

## 10. Third-party requirements

| Item | Account owner/provider | Cost owner |
| --- | --- | --- |
| Shopify subscription | Client | Client, paid directly to Shopify |
| ProSporter domain | Client | Client, paid directly to registrar |
| ProSporter frontend hosting | Service provider | Included in the Monthly Retainer |
| Paid Shopify app or plugin | Must be approved in writing before installation | Client, paid directly |

No new third-party cost may be incurred without prior written approval.

## 11. Phase 2 dates and review

Dates run in business days from Kickoff. Kickoff occurs when the agreement is signed and required access and materials have been received.

| Event | Target |
| --- | --- |
| **ProSporter storefront and migration delivered for review** | **10 business days from Kickoff** |
| Phase 2 Review Period closes | 7 days from delivery for review |
| ProSporter live and handover complete | 3 business days from written Phase 2 acceptance |

The Phase 2 Review Period is 7 days. The delivery date may be extended under the source agreement when a client dependency or response is delayed beyond the agreed allowance.

## 12. Phase 2 milestones

The acceptance milestone requires express written acceptance. Deemed acceptance does not apply to it.

| Milestone | Trigger | Amount |
| --- | --- | ---: |
| Phase 2 acceptance | Storefront built; migration complete; reconciliation and historical-order archive delivered; reviewed and accepted in writing | $250 |
| Phase 2 delivery and handover | ProSporter live and deployed; accepted; handover complete | $250 |
| **ProSporter total** |  | **$500** |

## 13. Warranty

The ProSporter Warranty Period is 30 days from its go-live date.

## 14. Ownership, access, and handover

Subject to full payment and the agreement's background-IP provisions, the client owns the custom ProSporter code, designs, and content produced for the project.

The client retains owner-level access to:

- The ProSporter domain and registrar account.
- The Shopify account.
- The ProSporter analytics property.
- Payment-gateway accounts.

The ProSporter handover includes:

- ProSporter source code in a Git repository transferred to a client-owned account.
- Shopify theme/fallback files and store configuration export.
- Database export where the ProSporter implementation uses a separate database.
- Complete WooCommerce historical-order archive.
- ProSporter design source files.
- Credentials and API keys created for ProSporter, transferred securely.
- Deployment, environment, and DNS documentation.
- Written instructions for content updates and redeployment.

Hosting infrastructure remains owned by the service provider while hosting is supplied through Ongoing Services. The delivered source must remain independently redeployable so the client is not locked to that provider.

The agreement includes 3 hours of transition assistance at no additional cost. Additional assistance is Out-of-Scope Work.

## 15. ProSporter ongoing services

ProSporter is added to the agreement's Ongoing Services at its go-live date without an additional retainer charge.

Applicable services include:

- Frontend hosting.
- Minor changes, updates, and support within the agreement's shared monthly time allowance.
- Dependency and platform security updates.
- Basic uptime and availability monitoring.
- Email support within the agreed response window.
- Backups under section 16.

The monthly time allowance is shared under the wider agreement and is not a ProSporter-only allocation.

The following remain out of scope for ongoing service:

- New features, pages, or major additions.
- Major redesigns or restructures.
- Custom integrations or new third-party platform connections.
- Work beyond the shared monthly time allowance.
- Content writing, photography, or ongoing SEO.

## 16. Hosting, backups, and security

| Matter | ProSporter requirement |
| --- | --- |
| Hosting | Service provider's nominated provider, included in Ongoing Services |
| Backup frequency | Daily automated backups of site data and configuration |
| Backup retention | 30 days rolling |
| Restoration | Best-efforts restoration from the most recent viable backup within 2 business days after written request |
| Security updates | Dependency and platform security updates applied as routine upkeep |
| Uptime | Best-efforts; no percentage guarantee for outages caused by Shopify, hosting, registrar, or payment providers |
| Monitoring | Basic uptime and availability monitoring with notification of extended outages |
| Data breach notification | Client notified within 72 hours after the service provider becomes aware of an incident affecting client data it holds |
| Data retention after termination | 30 days under the source agreement, after which service-provider copies may be permanently deleted |

## 17. Licensing and third-party software

- All themes, plugins, fonts, stock images, and third-party software included in ProSporter must be properly licensed for its intended use.
- The handover must include a written schedule naming each component, licence type, and recurring cost.
- Any recurring cost requires written approval before installation.

## 18. Marketing and portfolio restriction

The client opted out of the agreement's marketing and portfolio permission. ProSporter screenshots, descriptions, brand assets, athlete imagery, or member photography must not be used in marketing, a portfolio, a website, or social media without prior written approval.

## 19. Written approvals and response times

- Approvals, acceptances, variations, and formal notices must be in writing by email.
- Chat or messaging may be used for coordination but does not constitute formal approval.
- Requested content, access, and approvals are due within 7 days.
- A response taking 7 days or less does not affect the agreed dates.
- A longer response extends applicable dates day-for-day by the number of days beyond 7, subject to the source agreement.

## 20. Interpretation rule for this repository

When an LLM or contributor uses this file:

1. Treat every task as ProSporter ecommerce work unless the user expressly changes scope.
2. Do not introduce or plan unrelated websites, sports programs, club operations, feeds, or CMS work.
3. Treat the Next.js frontend as a conceptual implementation until Shopify data, cart, checkout, accounts, content, tests, and deployment are productionized.
4. Treat the authenticated WooCommerce/WordPress export at migration time as the source of truth.
5. Preserve the source PDF for contractual authority and use this document for repository-specific delivery context.
