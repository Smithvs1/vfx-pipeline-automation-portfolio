import Anthropic from '@anthropic-ai/sdk';
import { createClient } from '@supabase/supabase-js';
import ws from 'ws';
import { execSync } from 'node:child_process';
import { writeFileSync, readFileSync, unlinkSync, mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

// ─── Validate required env vars ───────────────────────────────────────────────
const REQUIRED_VARS = ['ANTHROPIC_API_KEY', 'SUPABASE_URL', 'SUPABASE_SERVICE_KEY'];
const missing = REQUIRED_VARS.filter(v => !process.env[v]);
if (missing.length) {
  console.error(`Missing required environment variables: ${missing.join(', ')}`);
  process.exit(1);
}

// ─── Clients ─────────────────────────────────────────────────────────────────
const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const supabase  = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_KEY,
  { realtime: { transport: ws } }
);

const PEXELS_KEY      = process.env.PEXELS_API_KEY;
const UNSPLASH_KEY    = process.env.UNSPLASH_ACCESS_KEY;
let   LINKEDIN_TOKEN  = process.env.LINKEDIN_ACCESS_TOKEN;
const LINKEDIN_ORG_ID = process.env.LINKEDIN_ORG_ID;

let   IG_TOKEN        = process.env.INSTAGRAM_ACCESS_TOKEN;
const IG_USER_ID      = process.env.INSTAGRAM_USER_ID;
const DRY_RUN         = process.env.DRY_RUN === 'true';
const META_APP_ID          = process.env.META_APP_ID;
const META_APP_SECRET      = process.env.META_APP_SECRET;
const LINKEDIN_CLIENT_ID   = process.env.LINKEDIN_CLIENT_ID;
const LINKEDIN_CLIENT_SEC  = process.env.LINKEDIN_CLIENT_SECRET;
let   LINKEDIN_REFRESH_TKN = process.env.LINKEDIN_REFRESH_TOKEN;
const JAMENDO_CLIENT_ID   = process.env.JAMENDO_CLIENT_ID;

// ─── Week / day helpers ───────────────────────────────────────────────────────

// JS getDay() returns 0=Sun; we use 0=Mon, 6=Sun
function getTodayDayOfWeek() {
  const jsDay = new Date().getDay();
  return jsDay === 0 ? 6 : jsDay - 1;
}

// ISO week number — determines Pexels vs Unsplash rotation
function getISOWeekNumber(date = new Date()) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86_400_000) + 1) / 7);
}

// Odd week → Pexels (with video for Reels), Even week → Unsplash
function getMediaSource() {
  return getISOWeekNumber() % 2 === 1 ? 'pexels' : 'unsplash';
}

async function getDaySlot() {
  const { data } = await supabase
    .from('si_cycle_tracker')
    .select('cycle_start')
    .eq('id', 1)
    .single();

  if (!data?.cycle_start) return 1;

  const start = new Date(data.cycle_start);
  const today = new Date();
  start.setHours(0, 0, 0, 0);
  today.setHours(0, 0, 0, 0);

  const elapsed = Math.floor((today - start) / 86_400_000);
  return (elapsed % 30) + 1;
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

// ─── Token store (Supabase) — auto-refresh Instagram tokens ─────────────────

async function ensureTokenStoreExists() {
  const { error } = await supabase.rpc('create_si_token_store_if_not_exists');
  if (error) {
    // Table may already exist or RPC not set up — fall back to direct create
    await supabase.from('si_token_store').select('key').limit(1);
  }
}

async function loadTokenFromStore(key) {
  const { data, error } = await supabase
    .from('si_token_store')
    .select('value, refreshed_at, expires_at')
    .eq('key', key)
    .single();
  if (error || !data) return null;
  return data;
}

async function saveTokenToStore(key, value, expiresInSeconds) {
  const now = new Date();
  const expiresAt = new Date(now.getTime() + expiresInSeconds * 1000);
  const { error } = await supabase
    .from('si_token_store')
    .upsert({
      key,
      value,
      refreshed_at: now.toISOString(),
      expires_at: expiresAt.toISOString(),
    }, { onConflict: 'key' });
  if (error) console.error(`  ⚠ Failed to save token to store: ${error.message}`);
}

async function refreshInstagramToken(currentToken) {
  if (!META_APP_ID || !META_APP_SECRET) {
    console.log('  ↷ META_APP_ID / META_APP_SECRET not set — skipping IG token refresh');
    return null;
  }

  const url = `https://graph.facebook.com/v25.0/oauth/access_token` +
    `?grant_type=fb_exchange_token` +
    `&client_id=${META_APP_ID}` +
    `&client_secret=${META_APP_SECRET}` +
    `&fb_exchange_token=${currentToken}`;

  const res = await fetch(url);
  const data = await res.json();

  if (data.error) {
    console.error(`  ⚠ IG token refresh failed: ${data.error.message}`);
    return null;
  }

  if (data.access_token) {
    const expiresIn = data.expires_in || 5184000; // default 60 days
    console.log(`  ✓ Instagram token refreshed (expires in ${Math.round(expiresIn / 86400)} days)`);
    await saveTokenToStore('instagram_access_token', data.access_token, expiresIn);
    return data.access_token;
  }

  return null;
}

async function refreshLinkedInToken() {
  if (!LINKEDIN_CLIENT_ID || !LINKEDIN_CLIENT_SEC || !LINKEDIN_REFRESH_TKN) {
    console.warn('  ⚠ LinkedIn refresh credentials missing — manual renewal required');
    console.warn('    → Go to LinkedIn Developer Portal → your app → OAuth 2.0 tools → generate new token');
    return null;
  }

  const params = new URLSearchParams({
    grant_type:    'refresh_token',
    refresh_token: LINKEDIN_REFRESH_TKN,
    client_id:     LINKEDIN_CLIENT_ID,
    client_secret: LINKEDIN_CLIENT_SEC,
  });

  const res = await fetch('https://www.linkedin.com/oauth/v2/accessToken', {
    method:  'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body:    params.toString(),
  });
  const data = await res.json();

  if (data.error) {
    console.error(`  ⚠ LinkedIn token refresh failed: ${data.error_description || data.error}`);
    return null;
  }

  if (data.access_token) {
    const expiresIn = data.expires_in || 5184000;
    console.log(`  ✓ LinkedIn token refreshed (expires in ${Math.round(expiresIn / 86400)} days)`);
    await saveTokenToStore('linkedin_access_token', data.access_token, expiresIn);

    // If a new refresh token was returned, save it too
    if (data.refresh_token) {
      const refreshExpiresIn = data.refresh_token_expires_in || 31536000;
      await saveTokenToStore('linkedin_refresh_token', data.refresh_token, refreshExpiresIn);
      LINKEDIN_REFRESH_TKN = data.refresh_token;
      console.log(`  ✓ LinkedIn refresh token also updated (expires in ${Math.round(refreshExpiresIn / 86400)} days)`);
    }

    return data.access_token;
  }

  return null;
}

async function loadAndRefreshTokens() {
  // Load Instagram token from Supabase (falls back to env var)
  try {
    const stored = await loadTokenFromStore('instagram_access_token');
    if (stored?.value) {
      IG_TOKEN = stored.value;
      const expiresAt = new Date(stored.expires_at);
      const daysLeft = Math.round((expiresAt - new Date()) / 86_400_000);
      console.log(`  ✓ Loaded IG token from store (expires in ${daysLeft} days)`);

      // Refresh if less than 14 days remaining
      if (daysLeft < 14) {
        console.log(`  ↻ Token expires soon — refreshing...`);
        const newToken = await refreshInstagramToken(IG_TOKEN);
        if (newToken) IG_TOKEN = newToken;
      }
    } else if (IG_TOKEN) {
      // First run — seed the store from env var and try to refresh
      console.log('  ↻ No stored IG token — seeding from env var and refreshing...');
      const newToken = await refreshInstagramToken(IG_TOKEN);
      if (newToken) IG_TOKEN = newToken;
      else await saveTokenToStore('instagram_access_token', IG_TOKEN, 5184000);
    }
  } catch (e) {
    console.error(`  ⚠ Token store error: ${e.message} — using env var`);
  }

  // Load LinkedIn token from Supabase (falls back to env var)
  try {
    const stored = await loadTokenFromStore('linkedin_access_token');
    if (stored?.value) {
      LINKEDIN_TOKEN = stored.value;
      const expiresAt = new Date(stored.expires_at);
      const daysLeft = Math.round((expiresAt - new Date()) / 86_400_000);
      console.log(`  ✓ Loaded LinkedIn token from store (expires in ${daysLeft} days)`);
      if (daysLeft < 14) {
        console.log(`  ↻ LinkedIn token expires soon — refreshing...`);
        const newToken = await refreshLinkedInToken();
        if (newToken) LINKEDIN_TOKEN = newToken;
      }
    } else if (LINKEDIN_TOKEN) {
      // Seed store — LinkedIn tokens default to 60 days
      await saveTokenToStore('linkedin_access_token', LINKEDIN_TOKEN, 5184000);
    }
  } catch (e) {
    console.error(`  ⚠ LinkedIn token store error: ${e.message} — using env var`);
  }

  // Load LinkedIn refresh token from store (falls back to env var)
  try {
    const stored = await loadTokenFromStore('linkedin_refresh_token');
    if (stored?.value) LINKEDIN_REFRESH_TKN = stored.value;
    else if (LINKEDIN_REFRESH_TKN) {
      // Seed — refresh tokens default to 12 months
      await saveTokenToStore('linkedin_refresh_token', LINKEDIN_REFRESH_TKN, 31536000);
    }
  } catch (e) { /* non-critical */ }
}

// ─── Image deduplication — no reuse for 90 days ─────────────────────────────

let recentlyUsedUrls = new Set();

async function loadRecentlyUsedImages() {
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - 90);

  const { data, error } = await supabase
    .from('si_generated_posts')
    .select('image_urls')
    .gte('scheduled_date', cutoff.toISOString().split('T')[0]);

  if (error) {
    console.warn(`  ⚠ Could not load recent images: ${error.message}`);
    return;
  }

  for (const row of (data || [])) {
    if (Array.isArray(row.image_urls)) {
      for (const url of row.image_urls) {
        // Normalize Unsplash URLs by stripping query params for comparison
        recentlyUsedUrls.add(normalizeUrl(url));
      }
    }
  }
  console.log(`  ✓ Loaded ${recentlyUsedUrls.size} recently used image URLs (90-day window)`);
}

function normalizeUrl(url) {
  try {
    const u = new URL(url);
    // For Unsplash, the path uniquely identifies the image
    if (u.hostname.includes('unsplash.com')) return u.origin + u.pathname;
    // For Pexels, the path also uniquely identifies the image
    if (u.hostname.includes('pexels.com')) return u.origin + u.pathname;
    return url;
  } catch {
    return url;
  }
}

function filterUnused(urls) {
  const fresh = urls.filter(u => !recentlyUsedUrls.has(normalizeUrl(u)));
  return fresh.length > 0 ? fresh : urls; // fall back to all if everything is used
}

function markUsed(urls) {
  for (const url of urls) recentlyUsedUrls.add(normalizeUrl(url));
}

// ─── Pexels ───────────────────────────────────────────────────────────────────

async function getPexelsImages(query, count = 1) {
  // Fetch extra results so we can skip recently used images
  const fetchCount = Math.max(count * 5, 10);
  const res  = await fetch(
    `https://api.pexels.com/v1/search?query=${encodeURIComponent(query)}&per_page=${fetchCount}&orientation=landscape`,
    { headers: { Authorization: PEXELS_KEY } }
  );
  const data = await res.json();

  if (!data.photos?.length) {
    const fb   = await fetch(
      `https://api.pexels.com/v1/search?query=professional+business+office&per_page=${fetchCount}&orientation=landscape`,
      { headers: { Authorization: PEXELS_KEY } }
    );
    const fbData = await fb.json();
    const allUrls = (fbData.photos || []).map(p => p.src.large2x || p.src.large);
    return filterUnused(allUrls).slice(0, count);
  }

  const allUrls = data.photos.map(p => p.src.large2x || p.src.large);
  return filterUnused(allUrls).slice(0, count);
}

async function getPexelsVideo(query) {
  // Try the specific query first, then broader fallbacks
  const queries = [
    query,
    'professional workplace',
    'business office modern',
    'career success diversity',
    'corporate team meeting',
  ];

  for (const q of queries) {
    try {
      const res = await fetch(
        `https://api.pexels.com/videos/search?query=${encodeURIComponent(q)}&per_page=5&size=medium`,
        { headers: { Authorization: PEXELS_KEY } }
      );
      const data = await res.json();
      if (data.videos?.length) {
        // Pick the first video that hasn't been recently used
        for (const vid of data.videos) {
          const url = getBestVideoFile(vid.video_files);
          if (url && !recentlyUsedUrls.has(normalizeUrl(url))) return url;
        }
        // All used — return first available
        const fallbackUrl = getBestVideoFile(data.videos[0].video_files);
        if (fallbackUrl) return fallbackUrl;
      }
    } catch (e) {
      console.warn(`  ⚠ Pexels video search failed for "${q}": ${e.message}`);
    }
  }

  return null;
}

function getBestVideoFile(files) {
  // Prefer HD (1280×720) — small enough to process, good quality
  const hd = files.find(f => f.quality === 'hd');
  return (hd || files[0])?.link || null;
}

// ─── Jamendo Music ────────────────────────────────────────────────────────────

async function getBackgroundMusic(query) {
  if (!JAMENDO_CLIENT_ID) return null;

  // Build search terms from topic — try specific, then generic
  const searchTerms = [
    query.replace(/[^\w\s]/g, '').split(/\s+/).slice(0, 3).join('+'),
    'corporate motivational',
    'upbeat inspirational',
    'positive background',
  ];

  for (const term of searchTerms) {
    try {
      const url = `https://api.jamendo.com/v3.0/tracks/?client_id=${JAMENDO_CLIENT_ID}`
        + `&format=json&limit=15&order=popularity_total`
        + `&search=${encodeURIComponent(term)}`
        + `&vocalinstrumental=instrumental&include=musicinfo`
        + `&audioformat=mp32`;
      const res  = await fetch(url);
      const data = await res.json();
      if (data.results?.length) {
        // Only pick tracks that allow download
        const downloadable = data.results.filter(t => t.audiodownload_allowed !== false);
        if (!downloadable.length) continue;

        const track = downloadable[Math.floor(Math.random() * Math.min(downloadable.length, 5))];
        // audiodownload gives a direct download URL; audio gives a streaming URL
        const trackUrl = track.audiodownload || track.audio;
        if (trackUrl) {
          // Append client_id if not already present
          const dlUrl = trackUrl.includes('client_id=')
            ? trackUrl
            : `${trackUrl}${trackUrl.includes('?') ? '&' : '?'}client_id=${JAMENDO_CLIENT_ID}`;
          return {
            url:    dlUrl,
            name:   track.name,
            artist: track.artist_name,
          };
        }
      }
    } catch (e) {
      console.warn(`  ⚠ Jamendo search failed for "${term}": ${e.message}`);
    }
  }

  return null;
}

async function uploadMixedVideo(buffer) {
  const fileName = `reel-${Date.now()}.mp4`;
  const { error: uploadErr } = await supabase.storage
    .from('reel-videos')
    .upload(fileName, buffer, { contentType: 'video/mp4', upsert: false });
  if (uploadErr) throw new Error(`Supabase upload: ${uploadErr.message}`);

  const { data: urlData } = supabase.storage
    .from('reel-videos')
    .getPublicUrl(fileName);
  return urlData.publicUrl;
}

async function mixVideoWithMusic(videoUrl, musicInfo) {
  const tmpDir = mkdtempSync(join(tmpdir(), 'reel-'));
  const videoPath  = join(tmpDir, 'video.mp4');
  const audioPath  = join(tmpDir, 'music.mp3');
  const outputPath = join(tmpDir, 'output.mp4');

  try {
    // Download video
    const vidRes = await fetch(videoUrl);
    const vidBuf = Buffer.from(await vidRes.arrayBuffer());
    writeFileSync(videoPath, vidBuf);

    // Download music
    const musRes = await fetch(musicInfo.url);
    const musBuf = Buffer.from(await musRes.arrayBuffer());
    writeFileSync(audioPath, musBuf);

    // Get video duration
    const durationStr = execSync(
      `ffprobe -v error -show_entries format=duration -of csv=p=0 "${videoPath}"`,
      { encoding: 'utf8' }
    ).trim();
    const duration = parseFloat(durationStr) || 15;

    // Try mixing with original audio + music first; if the video has no audio
    // stream, FFmpeg will fail — we catch that and retry without original audio.
    let mixed = false;
    try {
      execSync(
        `ffmpeg -y -i "${videoPath}" -i "${audioPath}" `
        + `-filter_complex "[1:a]volume=0.20,afade=t=out:st=${Math.max(0, duration - 2)}:d=2[music];`
        + `[0:a]volume=1.0[orig];`
        + `[orig][music]amix=inputs=2:duration=shortest[aout]" `
        + `-map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 128k -shortest "${outputPath}"`,
        { timeout: 120_000, stdio: 'pipe' }
      );
      mixed = true;
    } catch {
      // Video likely has no audio stream — use music-only approach
      execSync(
        `ffmpeg -y -i "${videoPath}" -i "${audioPath}" `
        + `-filter_complex "[1:a]volume=0.25,afade=t=out:st=${Math.max(0, duration - 2)}:d=2[aout]" `
        + `-map 0:v -map "[aout]" -c:v copy -c:a aac -b:a 128k -shortest "${outputPath}"`,
        { timeout: 120_000, stdio: 'pipe' }
      );
      mixed = true;
    }

    if (!mixed) throw new Error('FFmpeg mixing failed');

    // Read the output file
    const outputBuf = readFileSync(outputPath);

    // Upload to Supabase Storage
    return await uploadMixedVideo(outputBuf);
  } finally {
    // Clean up temp files
    try { unlinkSync(videoPath); } catch {}
    try { unlinkSync(audioPath); } catch {}
    try { unlinkSync(outputPath); } catch {}
  }
}

async function createVideoFromImage(imageUrl, musicInfo, durationSec = 10) {
  const tmpDir = mkdtempSync(join(tmpdir(), 'img2vid-'));
  const imgPath    = join(tmpDir, 'image.jpg');
  const audioPath  = join(tmpDir, 'music.mp3');
  const outputPath = join(tmpDir, 'output.mp4');

  try {
    // Download image
    const imgRes = await fetch(imageUrl);
    const imgBuf = Buffer.from(await imgRes.arrayBuffer());
    writeFileSync(imgPath, imgBuf);

    // Download music
    const musRes = await fetch(musicInfo.url);
    const musBuf = Buffer.from(await musRes.arrayBuffer());
    writeFileSync(audioPath, musBuf);

    // Create video from image with slow zoom (Ken Burns) + music
    // - zoompan: slow zoom from 100% → 115% over the duration
    // - 9:16 aspect for Instagram Reels (1080x1920)
    // - fade in/out for smooth transitions
    const fps = 30;
    const totalFrames = durationSec * fps;
    execSync(
      `ffmpeg -y -loop 1 -i "${imgPath}" -i "${audioPath}" `
      + `-filter_complex "`
      + `[0:v]scale=1920:1920:force_original_aspect_ratio=increase,`
      + `crop=1080:1920,`
      + `zoompan=z='min(zoom+0.0005,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${totalFrames}:s=1080x1920:fps=${fps},`
      + `fade=t=in:st=0:d=0.5,fade=t=out:st=${durationSec - 0.5}:d=0.5[v];`
      + `[1:a]volume=0.30,afade=t=in:st=0:d=1,afade=t=out:st=${durationSec - 2}:d=2[a]`
      + `" `
      + `-map "[v]" -map "[a]" -c:v libx264 -preset fast -crf 23 -c:a aac -b:a 128k `
      + `-t ${durationSec} -pix_fmt yuv420p -shortest "${outputPath}"`,
      { timeout: 180_000, stdio: 'pipe' }
    );

    const outputBuf = readFileSync(outputPath);
    return await uploadMixedVideo(outputBuf);
  } finally {
    try { unlinkSync(imgPath); } catch {}
    try { unlinkSync(audioPath); } catch {}
    try { unlinkSync(outputPath); } catch {}
  }
}

// ─── Unsplash ─────────────────────────────────────────────────────────────────

async function getUnsplashImages(query, count = 1) {
  // Fetch extra results so we can skip recently used images
  const fetchCount = Math.max(count * 5, 10);
  const res  = await fetch(
    `https://api.unsplash.com/search/photos?query=${encodeURIComponent(query)}&per_page=${fetchCount}&orientation=landscape`,
    { headers: { Authorization: `Client-ID ${UNSPLASH_KEY}` } }
  );
  const data = await res.json();

  if (!data.results?.length) {
    const fb     = await fetch(
      `https://api.unsplash.com/search/photos?query=diverse+professional+workplace&per_page=${fetchCount}&orientation=landscape`,
      { headers: { Authorization: `Client-ID ${UNSPLASH_KEY}` } }
    );
    const fbData = await fb.json();
    const allUrls = (fbData.results || []).map(p => p.urls.regular);
    return filterUnused(allUrls).slice(0, count);
  }

  const allUrls = data.results.map(p => p.urls.regular);
  return filterUnused(allUrls).slice(0, count);
}

// ─── Media router — picks source based on week + post type ───────────────────

async function getMedia(query, queries, postType, mediaSource) {
  let result;

  // Reels: try Pexels video (multiple fallback queries), then static image as last resort
  if (postType === 'REEL') {
    const videoUrl = PEXELS_KEY ? await getPexelsVideo(query) : null;
    if (videoUrl) {
      result = { urls: [videoUrl], isVideo: true };
    } else {
      console.warn('  ⚠ No video found on Pexels — falling back to static image');
      const imgs = mediaSource === 'pexels'
        ? await getPexelsImages(query, 1)
        : await getUnsplashImages(query, 1);
      result = { urls: imgs, isVideo: false };
    }
  } else if (mediaSource === 'pexels') {
    if (postType === 'CAROUSEL') {
      const urls = [];
      for (const q of queries) {
        const imgs = await getPexelsImages(q, 1);
        urls.push(...imgs);
        markUsed(imgs);
      }
      result = { urls, isVideo: false };
    } else {
      result = { urls: await getPexelsImages(query, 1), isVideo: false };
    }
  } else {
    // Unsplash weeks
    if (postType === 'CAROUSEL') {
      const urls = [];
      for (const q of queries) {
        const imgs = await getUnsplashImages(q, 1);
        urls.push(...imgs);
        markUsed(imgs);
      }
      result = { urls, isVideo: false };
    } else {
      result = { urls: await getUnsplashImages(query, 1), isVideo: false };
    }
  }

  // Mark all selected URLs as used for the rest of this run
  markUsed(result.urls);
  return result;
}

// ─── Claude ───────────────────────────────────────────────────────────────────

const CLAUDE_MODELS = [
  'claude-sonnet-4-6',
  'claude-sonnet-4-5-20250929',
  'claude-haiku-4-5-20251001',
];

async function generateContent(promptText, topic) {
  const filledPrompt = promptText.replace('{TOPIC}', topic);

  let message;
  let usedModel;
  for (const model of CLAUDE_MODELS) {
    try {
      message = await anthropic.messages.create({
        model,
        max_tokens: 2048,
        messages: [{ role: 'user', content: filledPrompt }],
      });
      usedModel = model;
      break;
    } catch (err) {
      if (err.status === 404) {
        console.warn(`  ⚠ Model ${model} not available, trying next...`);
        continue;
      }
      throw err;
    }
  }

  if (!message) throw new Error(`No Claude model available. Tried: ${CLAUDE_MODELS.join(', ')}`);
  console.log(`  ✓ Generated content using ${usedModel}`);

  const raw       = message.content[0].text;
  const jsonMatch = raw.match(/\{[\s\S]*\}/);
  if (!jsonMatch) throw new Error(`Claude did not return valid JSON.\nRaw: ${raw.slice(0, 300)}`);
  return JSON.parse(jsonMatch[0]);
}

// ─── LinkedIn ─────────────────────────────────────────────────────────────────

async function uploadImageToLinkedIn(imageUrl) {
  // Step 1: Initialize upload via REST API (Community Management API)
  const initRes = await fetch(
    'https://api.linkedin.com/rest/images?action=initializeUpload',
    {
      method:  'POST',
      headers: {
        Authorization:              `Bearer ${LINKEDIN_TOKEN}`,
        'Content-Type':              'application/json',
        'LinkedIn-Version':          '202601',
        'X-Restli-Protocol-Version': '2.0.0',
      },
      body: JSON.stringify({
        initializeUploadRequest: {
          owner: `urn:li:organization:${LINKEDIN_ORG_ID}`,
        },
      }),
    }
  );

  const initData = await initRes.json();
  if (!initRes.ok || !initData.value) {
    throw new Error(`LinkedIn image upload init failed (HTTP ${initRes.status}): ${JSON.stringify(initData)}`);
  }

  const uploadUrl = initData.value.uploadUrl;
  const imageUrn  = initData.value.image;
  if (!uploadUrl || !imageUrn) {
    throw new Error(`LinkedIn upload response missing uploadUrl or image: ${JSON.stringify(initData.value)}`);
  }

  // Step 2: Upload the binary image
  const imgRes    = await fetch(imageUrl);
  const imgBuffer = await imgRes.arrayBuffer();

  const uploadRes = await fetch(uploadUrl, {
    method:  'PUT',
    headers: {
      Authorization:  `Bearer ${LINKEDIN_TOKEN}`,
      'Content-Type': imgRes.headers.get('content-type') || 'image/jpeg',
    },
    body: imgBuffer,
  });

  if (!uploadRes.ok && uploadRes.status !== 201) {
    throw new Error(`LinkedIn image binary upload failed (HTTP ${uploadRes.status})`);
  }

  return imageUrn;
}

async function postToLinkedIn(commentary, imageUrns) {
  // Use REST API /rest/posts (Community Management API)
  const body = {
    author:         `urn:li:organization:${LINKEDIN_ORG_ID}`,
    commentary:     commentary.slice(0, 3000),
    visibility:     'PUBLIC',
    distribution:   { feedDistribution: 'MAIN_FEED', targetEntities: [], thirdPartyDistributionChannels: [] },
    lifecycleState: 'PUBLISHED',
  };

  if (imageUrns.length === 1) {
    body.content = {
      media: { title: 'SignedIt — interview prep and career content', id: imageUrns[0] },
    };
  } else if (imageUrns.length > 1) {
    body.content = {
      multiImage: {
        images: imageUrns.map(urn => ({ id: urn, altText: 'SignedIt career content' })),
      },
    };
  }

  const res = await fetch('https://api.linkedin.com/rest/posts', {
    method:  'POST',
    headers: {
      Authorization:              `Bearer ${LINKEDIN_TOKEN}`,
      'Content-Type':              'application/json',
      'LinkedIn-Version':          '202601',
      'X-Restli-Protocol-Version': '2.0.0',
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const err = await res.text();
    throw new Error(`LinkedIn API error ${res.status}: ${err}`);
  }
  return res.headers.get('x-restli-id') || res.headers.get('x-linkedin-id') || 'unknown';
}

// ─── Instagram ────────────────────────────────────────────────────────────────

async function waitForIgContainer(creationId, maxAttempts = 90) {
  for (let i = 0; i < maxAttempts; i++) {
    const res  = await fetch(
      `https://graph.facebook.com/v21.0/${creationId}?fields=status_code&access_token=${IG_TOKEN}`
    );
    const data = await res.json();
    if (data.status_code === 'FINISHED') return;
    if (data.status_code === 'ERROR') throw new Error(`Instagram container error: ${JSON.stringify(data)}`);
    await sleep(2000);
  }
  throw new Error(`Instagram container timed out after ${maxAttempts * 2} seconds`);
}

async function postToInstagramSingle(imageUrl, caption) {
  const createRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ image_url: imageUrl, media_type: 'IMAGE', caption, access_token: IG_TOKEN }),
    }
  );
  const createData = await createRes.json();
  if (createData.error) throw new Error(`IG create container: ${createData.error.message}`);

  await waitForIgContainer(createData.id);

  const pubRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media_publish`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ creation_id: createData.id, access_token: IG_TOKEN }),
    }
  );
  const pubData = await pubRes.json();
  if (pubData.error) throw new Error(`IG publish: ${pubData.error.message}`);
  return pubData.id;
}

async function postToInstagramReel(videoUrl, caption) {
  const createRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        video_url:    videoUrl,
        media_type:   'REELS',
        caption,
        share_to_feed: true,
        access_token: IG_TOKEN,
      }),
    }
  );
  const createData = await createRes.json();
  if (createData.error) throw new Error(`IG Reel container: ${createData.error.message}`);

  // Reels take longer to process — wait up to 60 seconds
  await waitForIgContainer(createData.id, 30);

  const pubRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media_publish`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ creation_id: createData.id, access_token: IG_TOKEN }),
    }
  );
  const pubData = await pubRes.json();
  if (pubData.error) throw new Error(`IG Reel publish: ${pubData.error.message}`);
  return pubData.id;
}

async function postToInstagramCarousel(imageUrls, caption) {
  const childIds = [];
  for (const url of imageUrls) {
    const res  = await fetch(
      `https://graph.facebook.com/v21.0/${IG_USER_ID}/media`,
      {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ image_url: url, is_carousel_item: true, access_token: IG_TOKEN }),
      }
    );
    const data = await res.json();
    if (data.error) throw new Error(`IG child container: ${data.error.message}`);
    childIds.push(data.id);
    await sleep(1000);
  }

  const carouselRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({
        media_type:  'CAROUSEL',
        children:     childIds.join(','),
        caption,
        access_token: IG_TOKEN,
      }),
    }
  );
  const carouselData = await carouselRes.json();
  if (carouselData.error) throw new Error(`IG carousel container: ${carouselData.error.message}`);

  await waitForIgContainer(carouselData.id);

  const pubRes = await fetch(
    `https://graph.facebook.com/v21.0/${IG_USER_ID}/media_publish`,
    {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ creation_id: carouselData.id, access_token: IG_TOKEN }),
    }
  );
  const pubData = await pubRes.json();
  if (pubData.error) throw new Error(`IG carousel publish: ${pubData.error.message}`);
  return pubData.id;
}

// ─── Caption builder ──────────────────────────────────────────────────────────

function buildCaption(generated) {
  return `${generated.caption || ''}\n\n${generated.hashtags || ''}`.trim();
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const today       = new Date().toISOString().split('T')[0];
  const dayOfWeek   = getTodayDayOfWeek();
  const daySlot     = await getDaySlot();
  const mediaSource = getMediaSource();
  const weekNum     = getISOWeekNumber();

  console.log(`\n=== SignedIt Daily Content | ${today} | week=${weekNum} (${mediaSource}) | day_of_week=${dayOfWeek} | slot=${daySlot} ===`);
  if (DRY_RUN) console.log('DRY RUN — content saved to Supabase but NOT posted to social media.\n');

  // Load stored tokens and auto-refresh if expiring soon
  if (!DRY_RUN) await loadAndRefreshTokens();

  // Load recently used images to prevent reuse within 90 days
  await loadRecentlyUsedImages();

  if (!DRY_RUN) {

    if (!IG_TOKEN || !IG_USER_ID) console.warn('⚠ Instagram credentials missing — Instagram posting will be skipped');

    // Validate LinkedIn token — requires "Community Management API" product
    // with w_organization_social + r_organization_social scopes
    if (LINKEDIN_TOKEN && LINKEDIN_ORG_ID) {
      try {
        const liRes = await fetch(
          `https://api.linkedin.com/rest/organizations/${LINKEDIN_ORG_ID}`,
          {
            headers: {
              Authorization:              `Bearer ${LINKEDIN_TOKEN}`,
              'LinkedIn-Version':          '202601',
              'X-Restli-Protocol-Version': '2.0.0',
            },
          }
        );
        if (liRes.ok) {
          try {
            const orgData = await liRes.json();
            console.log(`✓ LinkedIn token is valid (org: ${orgData.localizedName || LINKEDIN_ORG_ID})`);
          } catch {
            console.log('✓ LinkedIn token is valid');
          }
        } else {
          const liBody = await liRes.text();
          console.error(`⚠ LinkedIn validation failed (HTTP ${liRes.status}): ${liBody}`);
          console.error('  → Make sure "Community Management API" product is added in your LinkedIn Developer App');
          console.error('  → Token needs scopes: w_organization_social + r_organization_social');
        }
      } catch (e) {
        console.error(`⚠ LinkedIn token check error: ${e.message}`);
      }
    } else if (!LINKEDIN_TOKEN || !LINKEDIN_ORG_ID) {
      console.warn('⚠ LinkedIn credentials missing — LinkedIn posting will be skipped');
    }

    if (IG_TOKEN && IG_USER_ID) {
      try {
        const igRes = await fetch(`https://graph.facebook.com/v21.0/${IG_USER_ID}?fields=id,username&access_token=${IG_TOKEN}`);
        const igBody = await igRes.json();
        if (igBody.error) {
          console.error(`⚠ Instagram token validation failed: ${igBody.error.message} (code: ${igBody.error.code}, subcode: ${igBody.error.error_subcode || 'none'})`);
        } else {
          console.log(`✓ Instagram token is valid (account: @${igBody.username || igBody.id})`);
        }
      } catch (e) {
        console.error(`⚠ Instagram token check error: ${e.message}`);
      }
    }
  }
  if (!PEXELS_KEY && !UNSPLASH_KEY) console.warn('⚠ No image API keys — media fetching will fail');

  const { data: schedule, error: schedErr } = await supabase
    .from('si_day_schedule')
    .select('*')
    .eq('day_of_week', dayOfWeek);

  if (schedErr || !schedule?.length) {
    throw new Error(`Could not load schedule for day_of_week=${dayOfWeek}: ${schedErr?.message}`);
  }

  for (const slot of schedule) {
    console.log(`\n→ ${slot.post_type} (focus: ${slot.focus_type})`);

    try {
      // 1. Topic
      const { data: topic, error: topicErr } = await supabase
        .from('si_topics')
        .select('*')
        .eq('post_type', slot.post_type)
        .eq('day_slot', daySlot)
        .single();

      if (topicErr || !topic) {
        console.error(`  ✗ No topic found for ${slot.post_type} slot ${daySlot}`);
        continue;
      }
      console.log(`  Topic: "${topic.topic}"`);

      // 2. Prompt (A days randomly choose N or C)
      const promptFocus = slot.focus_type === 'A'
        ? (Math.random() < 0.5 ? 'N' : 'C')
        : slot.focus_type;

      const { data: prompt, error: promptErr } = await supabase
        .from('si_prompts')
        .select('*')
        .eq('post_type', slot.post_type)
        .eq('focus_type', promptFocus)
        .eq('active', true)
        .single();

      if (promptErr || !prompt) {
        console.error(`  ✗ No prompt for ${slot.post_type}/${promptFocus}`);
        continue;
      }

      // 3. Generate content via Claude
      const generated = await generateContent(prompt.prompt_text, topic.topic);
      console.log(`  ✓ Claude generated: "${generated.title || topic.topic}"`);

      // 4. Fetch media (alternates Pexels/Unsplash by week; Reels get video on Pexels weeks)
      const primaryQuery = generated.image_query || 'professional business career';
      const carouselQueries = slot.post_type === 'CAROUSEL'
        ? (generated.image_queries || Array(5).fill(primaryQuery))
        : [];

      const { urls: mediaUrls, isVideo } = await getMedia(
        primaryQuery,
        carouselQueries,
        slot.post_type,
        mediaSource
      );
      console.log(`  ✓ ${mediaSource} — ${mediaUrls.length} ${isVideo ? 'video' : 'image'}(s)`);

      // 5. Save to Supabase
      const { data: savedPost, error: saveErr } = await supabase
        .from('si_generated_posts')
        .insert({
          scheduled_date: today,
          post_type:      slot.post_type,
          focus_type:     slot.focus_type,
          topic_id:       topic.id,
          prompt_id:      prompt.id,
          topic_text:     topic.topic,
          generated_json: generated,
          image_urls:     mediaUrls,
          media_source:   mediaSource,
          safety_status:  'SAFE',
          publish_status: 'DRAFT',
        })
        .select()
        .single();

      if (saveErr) throw new Error(`Supabase insert failed: ${saveErr.message}`);
      console.log(`  ✓ Saved to Supabase (id: ${savedPost.id})`);

      if (DRY_RUN) {
        console.log('  ↷ Dry run — skipping social media posting');
        continue;
      }

      const caption = buildCaption(generated);

      // 6. Post to LinkedIn (images only — LinkedIn doesn't support video via this API)
      let linkedInPostId = null;
      if (!LINKEDIN_TOKEN || !LINKEDIN_ORG_ID) {
        console.log('  ↷ LinkedIn: credentials missing — skipping');
      } else if (!isVideo) {
        try {
          const imageUrns = [];
          for (const url of mediaUrls) {
            const urn = await uploadImageToLinkedIn(url);
            imageUrns.push(urn);
          }
          linkedInPostId = await postToLinkedIn(caption, imageUrns);
          console.log(`  ✓ LinkedIn posted (id: ${linkedInPostId})`);
        } catch (err) {
          console.error(`  ✗ LinkedIn failed: ${err.message}`);
        }
      } else {
        console.log('  ↷ LinkedIn: video posts not supported via API — skipping');
      }

      // 7. Post to Instagram
      // REEL → video Reel with music
      // STATIC → single image post
      // CAROUSEL → multi-image post
      let igPostId = null;
      try {
        if (isVideo) {
          // Already a video — mix in background music
          let reelUrl = mediaUrls[0];
          try {
            const music = await getBackgroundMusic(topic.topic);
            if (music) {
              console.log(`  ♪ Found music: "${music.name}" by ${music.artist}`);
              const mixedUrl = await mixVideoWithMusic(reelUrl, music);
              console.log(`  ✓ Mixed video + music — uploaded to Supabase Storage`);
              reelUrl = mixedUrl;
            } else {
              console.log('  ↷ No music found — posting video without background music');
            }
          } catch (mixErr) {
            console.warn(`  ⚠ Music mixing failed: ${mixErr.message} — posting video without music`);
          }
          igPostId = await postToInstagramReel(reelUrl, caption.slice(0, 2200));
        } else if (slot.post_type === 'CAROUSEL' && mediaUrls.length > 1) {
          igPostId = await postToInstagramCarousel(mediaUrls, caption.slice(0, 2200));
        } else {
          igPostId = await postToInstagramSingle(mediaUrls[0], caption.slice(0, 2200));
        }
        console.log(`  ✓ Instagram posted (id: ${igPostId})`);
      } catch (err) {
        console.error(`  ✗ Instagram failed: ${err.message}`);
      }

      // 8. Update Supabase with post IDs
      await supabase
        .from('si_generated_posts')
        .update({
          linkedin_post_id:  linkedInPostId,
          instagram_post_id: igPostId,
          publish_status:    (linkedInPostId || igPostId) ? 'PUBLISHED' : 'FAILED',
        })
        .eq('id', savedPost.id);

    } catch (err) {
      console.error(`  ✗ Fatal error for ${slot.post_type}: ${err.message}`);
      console.error(err.stack);
    }
  }

  console.log(`\n=== Done ===\n`);
}

main().catch(err => {
  console.error('Unhandled error:', err);
  process.exit(1);
});
