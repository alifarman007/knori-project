import { redirect } from "next/navigation";

/**
 * `/app` is not a screen. Plan §5.5 says arriving means picking up the last
 * conversation, and that decision lives in the chat screen where the
 * conversation list already is.
 */
export default function AppHomePage() {
  redirect("/app/chat");
}
