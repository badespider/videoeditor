import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  timeout: 300000, // 5 minutes for uploads
});

export interface JobProgress {
  job_id: string;
  status: string;
  progress: number;
  current_step: string;
  total_scenes: number;
  processed_scenes: number;
  error_message?: string;
  created_at: string;
  updated_at: string;
}

export interface JobResult {
  job_id: string;
  video_id: string;
  status: string;
  output_url?: string;
  scenes: Scene[];
  error_message?: string;
}

export interface Scene {
  index: number;
  start_time: number;
  end_time: number;
  duration: number;
  narration?: string;
  thumbnail_url?: string;
  processed: boolean;
}

export interface VideoUploadResponse {
  job_id: string;
  video_id: string;
  filename: string;
  status: string;
  message: string;
}

export interface VideoListItem {
  video_id: string;
  filename: string;
  status: string;
  created_at: string;
  output_url?: string;
}

// ============================================================================
// Character Management Types
// ============================================================================

export interface Character {
  id: string;
  name: string;
  aliases: string[];
  description: string;
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor';
  visual_traits: string[];
  confidence: number;
  first_appearance: number;
  source_video_no: string;
}

export interface CharacterCreate {
  name: string;
  aliases?: string[];
  description?: string;
  role?: 'protagonist' | 'antagonist' | 'supporting' | 'minor';
  visual_traits?: string[];
}

export interface CharacterUpdate {
  name?: string;
  aliases?: string[];
  description?: string;
  role?: 'protagonist' | 'antagonist' | 'supporting' | 'minor';
  visual_traits?: string[];
}

export interface SeriesInfo {
  series_id: string;
  character_count: number;
  last_updated: string | null;
}

export interface SeriesStats {
  series_id: string;
  character_count: number;
  speaker_mapping_count: number;
  last_updated: string | null;
  characters: { id: string; name: string; role: string; confidence: number }[];
}

// Upload video with optional script for Anchor Method
export const uploadVideo = async (
  file: File, 
  onProgress?: (progress: number) => void,
  script?: File,
  targetDurationMinutes?: number,
  characterGuide?: string,
  enableSceneMatcher?: boolean,
  enableCopyrightProtection?: boolean,
  seriesId?: string
): Promise<VideoUploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  
  // Add script file if provided (for Anchor Method)
  if (script) {
    formData.append('script', script);
  }
  
  // Add target duration if provided
  if (targetDurationMinutes !== undefined) {
    formData.append('target_duration_minutes', targetDurationMinutes.toString());
  }
  
  // Add character guide if provided (for proper character names in narration)
  if (characterGuide) {
    formData.append('character_guide', characterGuide);
  }
  
  // Add SceneMatcher toggle if enabled
  if (enableSceneMatcher) {
    formData.append('enable_scene_matcher', 'true');
  }

  // Add copyright protection toggle if enabled
  if (enableCopyrightProtection) {
    formData.append('enable_copyright_protection', 'true');
  }

  // Add series ID for character persistence across episodes
  if (seriesId) {
    formData.append('series_id', seriesId);
  }

  const response = await api.post<VideoUploadResponse>('/videos/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    onUploadProgress: (progressEvent) => {
      if (progressEvent.total && onProgress) {
        const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total);
        onProgress(progress);
      }
    },
  });

  return response.data;
};

// List videos
export const listVideos = async (page = 1, pageSize = 20): Promise<{ videos: VideoListItem[]; total: number }> => {
  const response = await api.get('/videos/', { params: { page, page_size: pageSize } });
  return response.data;
};

// Delete video
export const deleteVideo = async (videoId: string): Promise<void> => {
  await api.delete(`/videos/${videoId}`);
};

// Get job status
export const getJobStatus = async (jobId: string): Promise<JobProgress> => {
  const response = await api.get<JobProgress>(`/jobs/${jobId}`);
  return response.data;
};

// Get job result
export const getJobResult = async (jobId: string): Promise<JobResult> => {
  const response = await api.get<JobResult>(`/jobs/${jobId}/result`);
  return response.data;
};

// List jobs
export const listJobs = async (status?: string, limit = 50): Promise<JobProgress[]> => {
  const response = await api.get<JobProgress[]>('/jobs/', { params: { status, limit } });
  return response.data;
};

// Cancel job
export const cancelJob = async (jobId: string): Promise<void> => {
  await api.delete(`/jobs/${jobId}`);
};

// Retry job
export const retryJob = async (jobId: string): Promise<{ new_job_id: string }> => {
  const response = await api.post(`/jobs/${jobId}/retry`);
  return response.data;
};

// Get scenes
export const getScenes = async (jobId: string): Promise<{ scenes: Scene[] }> => {
  const response = await api.get(`/preview/${jobId}/scenes`);
  return response.data;
};

// Get output URL
export const getOutputUrl = async (jobId: string): Promise<{ url: string }> => {
  const response = await api.get(`/preview/${jobId}/output`);
  return response.data;
};

// Get download URL
export const getDownloadUrl = async (jobId: string): Promise<{ download_url: string; filename: string }> => {
  const response = await api.get(`/preview/${jobId}/download`);
  return response.data;
};

// WebSocket connection for job updates
export const connectJobWebSocket = (
  jobId: string,
  onUpdate: (data: JobProgress) => void,
  onComplete: (data: JobResult) => void,
  onError: (error: Event) => void
): WebSocket => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/jobs/${jobId}/ws`);

  ws.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    if (message.type === 'update' || message.type === 'initial') {
      onUpdate(message.data);
    } else if (message.type === 'complete') {
      onComplete(message.data);
    }
  };

  ws.onerror = onError;

  return ws;
};

// ============================================================================
// Character Management API
// ============================================================================

// List all series with saved characters
export const listSeries = async (): Promise<SeriesInfo[]> => {
  const response = await api.get<{ series: SeriesInfo[]; count: number }>('/characters/series');
  return response.data.series;
};

// Get characters for a series
export const getSeriesCharacters = async (seriesId: string): Promise<Character[]> => {
  // Normalize to lowercase for case-insensitive matching
  const normalizedId = seriesId.trim().toLowerCase();
  const response = await api.get<{ series_id: string; characters: Character[]; count: number }>(
    `/characters/series/${encodeURIComponent(normalizedId)}`
  );
  return response.data.characters;
};

// Get stats for a series
export const getSeriesStats = async (seriesId: string): Promise<SeriesStats> => {
  const response = await api.get<SeriesStats>(
    `/characters/series/${encodeURIComponent(seriesId)}/stats`
  );
  return response.data;
};

// Add a character to a series
export const addCharacter = async (seriesId: string, character: CharacterCreate): Promise<Character> => {
  const response = await api.post<Character>(
    `/characters/series/${encodeURIComponent(seriesId)}/characters`,
    character
  );
  return response.data;
};

// Update a character
export const updateCharacter = async (
  seriesId: string,
  charId: string,
  updates: CharacterUpdate
): Promise<Character> => {
  const response = await api.put<Character>(
    `/characters/series/${encodeURIComponent(seriesId)}/characters/${encodeURIComponent(charId)}`,
    updates
  );
  return response.data;
};

// Delete a character
export const deleteCharacter = async (seriesId: string, charId: string): Promise<void> => {
  await api.delete(
    `/characters/series/${encodeURIComponent(seriesId)}/characters/${encodeURIComponent(charId)}`
  );
};

// Clear all characters for a series
export const clearSeries = async (seriesId: string): Promise<{ message: string; deleted_characters: number }> => {
  const response = await api.delete<{ message: string; deleted_characters: number }>(
    `/characters/series/${encodeURIComponent(seriesId)}`
  );
  return response.data;
};

// ============================================================================
// Script Matching
// ============================================================================

export interface ScriptMatchResult {
  matching_id: string;
  matches: Array<{
    segment: {
      text: string;
      index: number;
    };
    matchedClip: {
      startTime: number;
      endTime: number;
      confidence: number;
    };
    alternatives: Array<{
      startTime: number;
      endTime: number;
      confidence: number;
    }>;
  }>;
  confidence_scores: number[];
}

export const matchScript = async (
  videoId: string,
  script: string
): Promise<ScriptMatchResult> => {
  const formData = new FormData();
  formData.append('script', script);

  const response = await api.post<ScriptMatchResult>(
    `/script-matching/${encodeURIComponent(videoId)}/match`,
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  );
  return response.data;
};

export default api;

