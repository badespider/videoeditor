import { NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET() {
  try {
    // Test basic connection
    const result = await prisma.$queryRaw`SELECT 1 as test`;
    
    // Check if tables exist
    const tables = await prisma.$queryRaw`
      SELECT table_name 
      FROM information_schema.tables 
      WHERE table_schema = 'public'
      ORDER BY table_name
    `;
    
    // Count users
    const userCount = await prisma.user.count();
    
    // Count accounts
    const accountCount = await prisma.account.count();
    
    return NextResponse.json({
      status: "connected",
      connectionTest: result,
      tables,
      counts: {
        users: userCount,
        accounts: accountCount,
      },
    });
  } catch (error: any) {
    console.error("Database debug error:", error);
    return NextResponse.json(
      {
        status: "error",
        error: error.message,
        code: error.code,
        meta: error.meta,
      },
      { status: 500 }
    );
  }
}

