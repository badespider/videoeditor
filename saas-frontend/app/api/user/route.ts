import { auth } from "@/auth";

import { prisma } from "@/lib/db";

export async function DELETE() {
  const session = await auth();
  const currentUser = session?.user;

  if (!currentUser?.id) {
    return new Response("Not authenticated", { status: 401 });
  }

  try {
    await prisma.user.delete({
      where: { id: currentUser.id },
    });
  } catch {
    return new Response("Internal server error", { status: 500 });
  }

  return new Response("User deleted successfully!", { status: 200 });
}
