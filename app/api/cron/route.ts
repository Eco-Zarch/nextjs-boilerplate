import { NextResponse } from "next/server";

export async function GET() {
	const timestamp = new Date().toISOString();
	console.log(`[CRON JOB] Executed at ${timestamp}`);

	return NextResponse.json({ message: `Cron job executed at ${timestamp}` });
}
