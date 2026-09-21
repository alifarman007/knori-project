import * as React from "react";

export interface AuthHeadingProps {
  title: string;
  description?: React.ReactNode;
}

export function AuthHeading({ title, description }: AuthHeadingProps) {
  return (
    <div className="mb-7">
      <h1 className="text-2xl">{title}</h1>
      {description ? <p className="mt-2 text-base text-ink-muted">{description}</p> : null}
    </div>
  );
}
