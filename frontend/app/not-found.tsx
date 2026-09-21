import Link from "next/link";

import { buttonStyles } from "@/components/ui/button";
import { Wordmark } from "@/components/wordmark";

export default function NotFound() {
  return (
    <div className="relative z-10 flex min-h-dvh flex-col items-center justify-center px-4 text-center">
      <Wordmark size="sm" />
      <p className="knori-eyebrow mt-10">404</p>
      <h1 className="mt-4 text-3xl">There is nothing at this address</h1>
      <p className="knori-prose mt-4 max-w-md">
        The link may be old, or the page may belong to someone else&rsquo;s account — KnoRI answers
        those the same way, on purpose.
      </p>
      <div className="mt-8 flex flex-col gap-3 sm:flex-row">
        <Link href="/" className={buttonStyles("primary", "md")}>
          Back to the start
        </Link>
        <Link href="/app" className={buttonStyles("secondary", "md")}>
          Go to your KnoRI
        </Link>
      </div>
    </div>
  );
}
