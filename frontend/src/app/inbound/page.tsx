import { InboundReview } from "@/components/inbound-review";
import { PageHeader } from "@/components/page-header";

export default function InboundPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Inbound Review"
        description="Review messages from the dedicated Gmail account before they become application events."
      />
      <InboundReview />
    </div>
  );
}
