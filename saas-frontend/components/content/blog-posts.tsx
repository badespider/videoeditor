import { BlogCard } from "@/components/content/blog-card";
import MaxWidthWrapper from "@/components/shared/max-width-wrapper";

type BlogPostItem = {
  _id: string;
  title: string;
  description?: string;
  date: string;
  slug: string;
  image: string;
  blurDataURL?: string;
};

export function BlogPosts({ posts }: { posts: BlogPostItem[] }) {
  return (
    <MaxWidthWrapper className="py-10">
      <div className="flex flex-col gap-3">
        <h1 className="font-heading text-3xl text-foreground sm:text-4xl">
          Blog
        </h1>
        <p className="max-w-2xl text-muted-foreground">
          Workflow tips, copyright-safe strategies, and production guides for
          recap creators.
        </p>
      </div>

      <div className="mt-8 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {posts.map((post, idx) => (
          <BlogCard key={post._id} data={post} priority={idx <= 2} />
        ))}
      </div>
    </MaxWidthWrapper>
  );
}


