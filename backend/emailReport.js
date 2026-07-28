import nodemailer from "nodemailer";

// Backend-only, on purpose — no frontend wiring, no UI for entering a
// recipient. Configured entirely via env vars (see .env.example) so it's
// inert until real SMTP credentials + a recipient are actually set, the
// same "safe until configured" pattern already used for HF_TOKEN elsewhere
// in this project. Called from server.js's scheduled job, never from any
// request handler a browser can reach.
function emailConfigured() {
  return Boolean(
    process.env.SMTP_HOST &&
    process.env.SMTP_USER &&
    process.env.SMTP_PASS &&
    process.env.REPORT_EMAIL_TO
  );
}

function buildTransporter() {
  return nodemailer.createTransport({
    host: process.env.SMTP_HOST,
    port: Number(process.env.SMTP_PORT) || 587,
    secure: process.env.SMTP_SECURE === "true", // true for port 465, false for 587/STARTTLS
    auth: {
      user: process.env.SMTP_USER,
      pass: process.env.SMTP_PASS,
    },
  });
}

/** Sends the just-generated report by email, attaching the same self-
 * contained HTML report.html the archive step just wrote. No-ops (logs and
 * returns false) rather than throwing if SMTP/recipient env vars aren't
 * set, so a missing email config never fails the scheduled job overall —
 * matches how a missing HF_TOKEN degrades gracefully rather than crashing
 * narration. Returns true if an email was actually sent. */
export async function sendReportEmail(factSheet, reportHtmlPath) {
  if (!emailConfigured()) {
    console.log("[email] skipped — SMTP_HOST/SMTP_USER/SMTP_PASS/REPORT_EMAIL_TO not all set in .env");
    return false;
  }

  const transporter = buildTransporter();
  const subject = `MP Weekly Mandi Summary — ${factSheet.week_start} to ${factSheet.week_end} (${factSheet.snapshot_id})`;
  const recipients = process.env.REPORT_EMAIL_TO.split(",").map((s) => s.trim()).filter(Boolean);

  await transporter.sendMail({
    from: process.env.REPORT_EMAIL_FROM || process.env.SMTP_USER,
    to: recipients,
    subject,
    text: (
      `Madhya Pradesh weekly mandi summary for ${factSheet.week_start} to ${factSheet.week_end} ` +
      `is attached (snapshot ${factSheet.snapshot_id}).\n\n` +
      `This is an automated message from the Sunday-night report generation job.`
    ),
    attachments: [
      {
        filename: `${factSheet.snapshot_id}.html`,
        path: reportHtmlPath,
        contentType: "text/html",
      },
    ],
  });

  console.log(`[email] sent to ${recipients.join(", ")} (${subject})`);
  return true;
}
