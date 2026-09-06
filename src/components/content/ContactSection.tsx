import "server-only";

/**
 * Decides, at render time, whether `/contact` gets a working form.
 *
 * The contract (schedule acceptance criterion 3) is that a form delivers to the
 * client-nominated address. That address has not been nominated yet, so
 * delivery is configured entirely by environment variable and this component is
 * the graceful-degradation half:
 *
 *   configured (any environment) -> the real form
 *   development, unconfigured    -> the real form, delivering to the log adapter
 *   production, unconfigured     -> no form at all, plus a pointer back to the
 *                                   phone number and email address that the
 *                                   migrated page copy already renders above
 *
 * A rendered form with no delivery would accept a message and lose it, which is
 * worse for the visitor than being told to phone. `warnIfUnconfigured()` logs
 * that state once per instance.
 */
import { connection } from "next/server";

import { ContactForm } from "./ContactForm";
import { issueContactFormToken } from "@/lib/contact/config";
import { deliveryAdapter, warnIfUnconfigured } from "@/lib/contact/deliver";

export async function ContactSection() {
  // Request-time, always. Two reasons: the timing token has to be stamped per
  // request (`/contact` is otherwise prerendered by `generateStaticParams` with
  // a one-hour revalidate, which would bake one timestamp into a cached page
  // and hand every visitor a token that is already stale), and the configured/
  // unconfigured decision below must reflect the runtime environment rather
  // than whatever was set when the deployment was built. This bails only this
  // path out of prerendering; every other `(content)` handle stays static.
  await connection();

  if (deliveryAdapter() === "none") {
    warnIfUnconfigured();
    return (
      <section className="mt-12 border-t border-line pt-10">
        <h2 className="display text-2xl sm:text-3xl">Get in touch</h2>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted">
          Our contact form is being set up. In the meantime, use the phone number
          or email address above and we will come back to you within one business
          day.
        </p>
      </section>
    );
  }

  return <ContactForm formToken={await issueContactFormToken()} />;
}
