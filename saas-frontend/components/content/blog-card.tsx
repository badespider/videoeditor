import Link from "next/link";

import { cn, formatDate } from "@/lib/utils";
import BlurImage from "@/components/shared/blur-image";

type BlogCardPost = {
  _id: string;
  title: string;
  description?: string;
  date: string;
  slug: string;
  image: string;
  blurDataURL?: string;
};

export function BlogCard({
  data,
  priority = false,
  className,
}: {
  data: BlogCardPost;
  priority?: boolean;
  className?: string;
}) {
  return (
    <Link
      href={data.slug}
      className={cn(
        "group flex flex-col overflow-hidden rounded-xl border bg-card shadow-sm transition-colors hover:bg-muted/40",
        className,
      )}
    >
      <div className="relative overflow-hidden border-b">
        <BlurImage
          alt={data.title}
          src={data.image}
          width={1200}
          height={630}
          sizes="(max-width: 768px) 100vw, 400px"
          className="aspect-[1200/630] object-cover transition-transform duration-300 group-hover:scale-[1.02]"
          placeholder={data.blurDataURL ? "blur" : "empty"}
          blurDataURL={data.blurDataURL}
          priority={priority}
        />
      </div>

      <div className="flex flex-1 flex-col gap-2 p-4">
        <p className="text-xs text-muted-foreground">{formatDate(data.date)}</p>
        <h3 className="font-heading text-lg text-foreground">{data.title}</h3>
        {data.description ? (
          <p className="line-clamp-2 text-sm text-muted-foreground">
            {data.description}
          </p>
        ) : null}
        <div className="mt-auto pt-2 text-sm font-medium text-foreground/90">
          Read article
        </div>
      </div>
    </Link>
  );
}


