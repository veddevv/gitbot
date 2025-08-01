import { Suspense } from "react";
import CompleteClient from "./component";

export default function AuthCompletePage() {
  return (
    <Suspense fallback={<div className="text-center mt-10 text-white">Loading...</div>}>
      <CompleteClient />
    </Suspense>
  );
}

