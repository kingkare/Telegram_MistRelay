#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{
    collections::HashMap,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::{Instant, SystemTime, UNIX_EPOCH},
};

use futures_util::StreamExt;
use reqwest::{
    header::{HeaderMap, ACCEPT_RANGES, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_RANGE, RANGE},
    Client, StatusCode,
};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, State};
use tokio::{
    fs,
    io::{AsyncReadExt, AsyncWriteExt},
    sync::Mutex,
};

type DesktopResult<T> = Result<T, String>;
type SharedChunks = Arc<Mutex<Vec<DownloadChunk>>>;
type CancelFlag = Arc<AtomicBool>;

const DOWNLOAD_PROGRESS_EVENT: &str = "pc-download-progress";
const DOWNLOAD_COMPLETED_EVENT: &str = "pc-download-completed";
const DOWNLOAD_FAILED_EVENT: &str = "pc-download-failed";
const DOWNLOAD_CANCELLED_EVENT: &str = "pc-download-cancelled";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum DownloadTaskStatus {
    Queued,
    Downloading,
    Completed,
    Failed,
    Cancelled,
    Interrupted,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
enum DownloadChunkStatus {
    Queued,
    Downloading,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DownloadError {
    task_id: String,
    code: String,
    message: String,
    retryable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DownloadChunk {
    index: u32,
    start: u64,
    end: u64,
    downloaded_bytes: u64,
    status: DownloadChunkStatus,
    error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DownloadTask {
    id: String,
    source_url: String,
    file_name: String,
    save_path: String,
    total_bytes: u64,
    downloaded_bytes: u64,
    status: DownloadTaskStatus,
    threads: u8,
    created_at: String,
    updated_at: String,
    error: Option<DownloadError>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct DownloadProgressEvent {
    task_id: String,
    status: DownloadTaskStatus,
    total_bytes: u64,
    downloaded_bytes: u64,
    speed_bytes_per_second: u64,
    chunks: Vec<DownloadChunk>,
}

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DownloadTaskSignal {
    task_id: String,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StartDownloadRequest {
    id: Option<String>,
    source_url: String,
    file_name: Option<String>,
    save_path: String,
    threads: Option<u8>,
}

#[derive(Debug, Clone)]
struct RangeProbe {
    total_bytes: Option<u64>,
    supports_ranges: bool,
    file_name: Option<String>,
}

struct DownloadRuntimeState {
    cancellations: Mutex<HashMap<String, CancelFlag>>,
}

impl Default for DownloadRuntimeState {
    fn default() -> Self {
        Self {
            cancellations: Mutex::new(HashMap::new()),
        }
    }
}

impl DownloadRuntimeState {
    async fn register(&self, task_id: String, cancel_flag: CancelFlag) {
        self.cancellations.lock().await.insert(task_id, cancel_flag);
    }

    async fn unregister(&self, task_id: &str) {
        self.cancellations.lock().await.remove(task_id);
    }

    async fn cancel(&self, task_id: &str) -> bool {
        let cancellations = self.cancellations.lock().await;
        if let Some(cancel_flag) = cancellations.get(task_id) {
            cancel_flag.store(true, Ordering::SeqCst);
            true
        } else {
            false
        }
    }
}

#[derive(Debug, serde::Deserialize)]
struct SaveFileOptions {
    default_name: Option<String>,
}

#[derive(Debug, serde::Deserialize)]
struct SystemNotificationOptions {
    title: String,
    body: String,
}

fn not_implemented(command: &str) -> String {
    format!("{command} is not implemented yet")
}

fn current_timestamp() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
        .to_string()
}

fn current_timestamp_millis() -> String {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .to_string()
}

fn make_download_error(
    task_id: &str,
    code: impl Into<String>,
    message: impl Into<String>,
    retryable: bool,
) -> DownloadError {
    DownloadError {
        task_id: task_id.to_string(),
        code: code.into(),
        message: message.into(),
        retryable,
    }
}

fn content_length(headers: &HeaderMap) -> Option<u64> {
    headers
        .get(CONTENT_LENGTH)
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok())
}

fn accepts_ranges(headers: &HeaderMap) -> bool {
    headers
        .get(ACCEPT_RANGES)
        .and_then(|value| value.to_str().ok())
        .map(|value| value.to_ascii_lowercase().contains("bytes"))
        .unwrap_or(false)
}

fn total_from_content_range(headers: &HeaderMap) -> Option<u64> {
    let value = headers.get(CONTENT_RANGE)?.to_str().ok()?;
    let (_, total) = value.split_once('/')?;
    if total == "*" {
        None
    } else {
        total.parse::<u64>().ok()
    }
}

fn file_name_from_content_disposition(headers: &HeaderMap) -> Option<String> {
    let value = headers.get(CONTENT_DISPOSITION)?.to_str().ok()?;

    for part in value.split(';').map(str::trim) {
        if let Some(raw_name) = part.strip_prefix("filename*=") {
            let decoded_name = raw_name
                .split_once("''")
                .map(|(_, name)| name)
                .unwrap_or(raw_name);
            let file_name = decoded_name.trim_matches('"').trim();
            if !file_name.is_empty() {
                return Some(file_name.to_string());
            }
        }

        if let Some(raw_name) = part.strip_prefix("filename=") {
            let file_name = raw_name.trim_matches('"').trim();
            if !file_name.is_empty() {
                return Some(file_name.to_string());
            }
        }
    }

    None
}

fn file_name_from_url(source_url: &str) -> Option<String> {
    let url = reqwest::Url::parse(source_url).ok()?;
    let candidate = url
        .path_segments()
        .and_then(|segments| segments.filter(|segment| !segment.is_empty()).last())?;

    Some(candidate.to_string()).filter(|name| !name.is_empty())
}

fn is_retryable_status(status: StatusCode) -> bool {
    status.is_server_error()
        || status == StatusCode::REQUEST_TIMEOUT
        || status == StatusCode::TOO_MANY_REQUESTS
}

fn status_download_error(task_id: &str, code: &str, status: StatusCode) -> DownloadError {
    if status == StatusCode::UNAUTHORIZED {
        return make_download_error(task_id, "unauthorized", "登录已过期", false);
    }

    if status == StatusCode::RANGE_NOT_SATISFIABLE {
        return make_download_error(
            task_id,
            "range_not_satisfiable",
            "服务器拒绝当前分片范围",
            true,
        );
    }

    make_download_error(
        task_id,
        code,
        format!("download request failed with HTTP {status}"),
        is_retryable_status(status),
    )
}

fn is_disk_full(error: &std::io::Error) -> bool {
    matches!(error.raw_os_error(), Some(28) | Some(112))
}

fn io_download_error(
    task_id: &str,
    fallback_code: &str,
    message: impl Into<String>,
    error: &std::io::Error,
) -> DownloadError {
    if is_disk_full(error) {
        make_download_error(task_id, "disk_full", message, false)
    } else {
        make_download_error(task_id, fallback_code, message, false)
    }
}

fn cancelled_download_error(task_id: &str) -> DownloadError {
    make_download_error(task_id, "cancelled", "下载已取消", false)
}

fn is_cancelled_error(error: &DownloadError) -> bool {
    error.code == "cancelled"
}

fn emit_cancelled(app: &AppHandle, task_id: &str) {
    let _ = app.emit(
        DOWNLOAD_CANCELLED_EVENT,
        DownloadTaskSignal {
            task_id: task_id.to_string(),
        },
    );
}

fn clean_file_name(file_name: &str) -> String {
    let cleaned = file_name
        .chars()
        .map(|ch| match ch {
            '/' | '\\' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '_',
            _ => ch,
        })
        .collect::<String>();

    if cleaned.trim().is_empty() {
        "download.bin".to_string()
    } else {
        cleaned
    }
}

fn resolve_final_path(save_path: &str, file_name: &str) -> PathBuf {
    let path = PathBuf::from(save_path);
    if path.is_dir() || save_path.ends_with('/') || save_path.ends_with('\\') {
        path.join(clean_file_name(file_name))
    } else {
        path
    }
}

fn temp_path_for(final_path: &Path, task_id: &str, suffix: &str) -> PathBuf {
    let base_name = final_path
        .file_name()
        .and_then(|name| name.to_str())
        .filter(|name| !name.is_empty())
        .unwrap_or("download");

    let safe_task_id = clean_file_name(task_id);
    final_path.with_file_name(format!(".{base_name}.{safe_task_id}.{suffix}.part"))
}

fn split_chunks(total_bytes: u64, requested_threads: u8) -> Vec<DownloadChunk> {
    let thread_count = u64::from(requested_threads.max(1)).min(total_bytes.max(1));
    let chunk_size = (total_bytes + thread_count - 1) / thread_count;
    let mut chunks = Vec::new();

    for index in 0..thread_count {
        let start = index * chunk_size;
        if start >= total_bytes {
            break;
        }

        let end = ((index + 1) * chunk_size).saturating_sub(1).min(total_bytes - 1);
        chunks.push(DownloadChunk {
            index: index as u32,
            start,
            end,
            downloaded_bytes: 0,
            status: DownloadChunkStatus::Queued,
            error: None,
        });
    }

    chunks
}

async fn set_chunk_status(
    chunks: &SharedChunks,
    index: u32,
    status: DownloadChunkStatus,
    error: Option<String>,
) {
    let mut chunks = chunks.lock().await;
    if let Some(chunk) = chunks.iter_mut().find(|chunk| chunk.index == index) {
        chunk.status = status;
        chunk.error = error;
    }
}

async fn set_chunk_downloaded(chunks: &SharedChunks, index: u32, downloaded_bytes: u64) {
    let mut chunks = chunks.lock().await;
    if let Some(chunk) = chunks.iter_mut().find(|chunk| chunk.index == index) {
        chunk.downloaded_bytes = downloaded_bytes;
    }
}

async fn mark_incomplete_chunks(
    chunks: &SharedChunks,
    status: DownloadChunkStatus,
    error: Option<String>,
) {
    let mut chunks = chunks.lock().await;
    for chunk in chunks.iter_mut() {
        if matches!(chunk.status, DownloadChunkStatus::Completed) {
            continue;
        }
        chunk.status = status.clone();
        chunk.error = error.clone();
    }
}

async fn emit_progress(
    app: &AppHandle,
    task_id: &str,
    status: DownloadTaskStatus,
    total_bytes: u64,
    chunks: &SharedChunks,
    started_at: Instant,
) {
    let chunk_snapshot = chunks.lock().await.clone();
    let downloaded_bytes = chunk_snapshot
        .iter()
        .map(|chunk| chunk.downloaded_bytes)
        .sum::<u64>();
    let elapsed_seconds = started_at.elapsed().as_secs_f64();
    let speed_bytes_per_second = if elapsed_seconds > 0.0 {
        (downloaded_bytes as f64 / elapsed_seconds).round() as u64
    } else {
        0
    };

    let _ = app.emit(
        DOWNLOAD_PROGRESS_EVENT,
        DownloadProgressEvent {
            task_id: task_id.to_string(),
            status,
            total_bytes,
            downloaded_bytes,
            speed_bytes_per_second,
            chunks: chunk_snapshot,
        },
    );
}

fn emit_failed(app: &AppHandle, error: &DownloadError) {
    let _ = app.emit(DOWNLOAD_FAILED_EVENT, error);
}

async fn probe_range_support(client: &Client, source_url: &str) -> RangeProbe {
    let mut total_bytes = None;
    let mut supports_ranges = false;
    let mut file_name = None;

    if let Ok(response) = client.head(source_url).send().await {
        let headers = response.headers();
        total_bytes = content_length(headers);
        supports_ranges = accepts_ranges(headers) && total_bytes.unwrap_or(0) > 0;
        file_name = file_name_from_content_disposition(headers);
    }

    if supports_ranges {
        return RangeProbe {
            total_bytes,
            supports_ranges,
            file_name,
        };
    }

    if let Ok(response) = client
        .get(source_url)
        .header(RANGE, "bytes=0-0")
        .send()
        .await
    {
        let headers = response.headers();
        if file_name.is_none() {
            file_name = file_name_from_content_disposition(headers);
        }

        if response.status() == StatusCode::PARTIAL_CONTENT {
            total_bytes = total_from_content_range(headers).or_else(|| content_length(headers));
            supports_ranges = total_bytes.unwrap_or(0) > 0;
        } else if total_bytes.is_none() {
            total_bytes = content_length(headers);
        }
    }

    RangeProbe {
        total_bytes,
        supports_ranges,
        file_name,
    }
}

async fn download_range_chunk(
    client: Client,
    app: AppHandle,
    task_id: String,
    source_url: String,
    temp_path: PathBuf,
    chunk: DownloadChunk,
    total_bytes: u64,
    chunks: SharedChunks,
    started_at: Instant,
    cancel_flag: CancelFlag,
) -> Result<(), DownloadError> {
    set_chunk_status(&chunks, chunk.index, DownloadChunkStatus::Downloading, None).await;
    emit_progress(
        &app,
        &task_id,
        DownloadTaskStatus::Downloading,
        total_bytes,
        &chunks,
        started_at,
    )
    .await;

    if cancel_flag.load(Ordering::SeqCst) {
        let error = cancelled_download_error(&task_id);
        set_chunk_status(
            &chunks,
            chunk.index,
            DownloadChunkStatus::Cancelled,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    let response = match client
        .get(&source_url)
        .header(RANGE, format!("bytes={}-{}", chunk.start, chunk.end))
        .send()
        .await
    {
        Ok(response) => response,
        Err(error) => {
            let error = make_download_error(
                &task_id,
                "request_failed",
                format!("failed to request chunk {}: {error}", chunk.index),
                true,
            );
            set_chunk_status(
                &chunks,
                chunk.index,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }
    };

    if response.status() != StatusCode::PARTIAL_CONTENT {
        let error = status_download_error(&task_id, "range_not_satisfied", response.status());
        set_chunk_status(
            &chunks,
            chunk.index,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    let mut file = match fs::File::create(&temp_path).await {
        Ok(file) => file,
        Err(error) => {
            let error = io_download_error(
                &task_id,
                "temp_file_create_failed",
                format!("failed to create temporary chunk file: {error}"),
                &error,
            );
            set_chunk_status(
                &chunks,
                chunk.index,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }
    };

    let expected_bytes = chunk.end - chunk.start + 1;
    let mut downloaded_bytes = 0;
    let mut last_emit = Instant::now();
    let mut stream = response.bytes_stream();

    while let Some(item) = stream.next().await {
        if cancel_flag.load(Ordering::SeqCst) {
            let error = cancelled_download_error(&task_id);
            set_chunk_status(
                &chunks,
                chunk.index,
                DownloadChunkStatus::Cancelled,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }

        let bytes = match item {
            Ok(bytes) => bytes,
            Err(error) => {
                let error = make_download_error(
                    &task_id,
                    "stream_failed",
                    format!("failed while reading chunk {}: {error}", chunk.index),
                    true,
                );
                set_chunk_status(
                    &chunks,
                    chunk.index,
                    DownloadChunkStatus::Failed,
                    Some(error.message.clone()),
                )
                .await;
                return Err(error);
            }
        };

        if let Err(error) = file.write_all(&bytes).await {
            let error = io_download_error(
                &task_id,
                "write_failed",
                format!("failed while writing chunk {}: {error}", chunk.index),
                &error,
            );
            set_chunk_status(
                &chunks,
                chunk.index,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }

        downloaded_bytes += bytes.len() as u64;
        set_chunk_downloaded(&chunks, chunk.index, downloaded_bytes).await;

        if last_emit.elapsed().as_millis() >= 200 {
            emit_progress(
                &app,
                &task_id,
                DownloadTaskStatus::Downloading,
                total_bytes,
                &chunks,
                started_at,
            )
            .await;
            last_emit = Instant::now();
        }
    }

    if let Err(error) = file.flush().await {
        let error = io_download_error(
            &task_id,
            "flush_failed",
            format!("failed to flush chunk {}: {error}", chunk.index),
            &error,
        );
        set_chunk_status(
            &chunks,
            chunk.index,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    if downloaded_bytes != expected_bytes {
        let error = make_download_error(
            &task_id,
            "chunk_size_mismatch",
            format!(
                "chunk {} expected {expected_bytes} bytes but downloaded {downloaded_bytes}",
                chunk.index
            ),
            true,
        );
        set_chunk_status(
            &chunks,
            chunk.index,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    set_chunk_status(&chunks, chunk.index, DownloadChunkStatus::Completed, None).await;
    emit_progress(
        &app,
        &task_id,
        DownloadTaskStatus::Downloading,
        total_bytes,
        &chunks,
        started_at,
    )
    .await;

    Ok(())
}

async fn download_single_file(
    client: &Client,
    app: &AppHandle,
    task_id: &str,
    source_url: &str,
    temp_path: &Path,
    total_bytes: u64,
    chunks: &SharedChunks,
    started_at: Instant,
    cancel_flag: CancelFlag,
) -> Result<u64, DownloadError> {
    set_chunk_status(chunks, 0, DownloadChunkStatus::Downloading, None).await;
    emit_progress(
        app,
        task_id,
        DownloadTaskStatus::Downloading,
        total_bytes,
        chunks,
        started_at,
    )
    .await;

    if cancel_flag.load(Ordering::SeqCst) {
        let error = cancelled_download_error(task_id);
        set_chunk_status(
            chunks,
            0,
            DownloadChunkStatus::Cancelled,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    let response = match client.get(source_url).send().await {
        Ok(response) => response,
        Err(error) => {
            let error = make_download_error(
                task_id,
                "request_failed",
                format!("failed to request download: {error}"),
                true,
            );
            set_chunk_status(
                chunks,
                0,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }
    };

    if !response.status().is_success() {
        let error = status_download_error(task_id, "download_failed", response.status());
        set_chunk_status(
            chunks,
            0,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    let response_total_bytes = response.content_length().unwrap_or(total_bytes);
    if response_total_bytes > 0 {
        let mut chunks = chunks.lock().await;
        if let Some(chunk) = chunks.iter_mut().find(|chunk| chunk.index == 0) {
            chunk.end = response_total_bytes.saturating_sub(1);
        }
    }

    let mut file = match fs::File::create(temp_path).await {
        Ok(file) => file,
        Err(error) => {
            let error = io_download_error(
                task_id,
                "temp_file_create_failed",
                format!("failed to create temporary download file: {error}"),
                &error,
            );
            set_chunk_status(
                chunks,
                0,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }
    };

    let mut downloaded_bytes = 0;
    let mut last_emit = Instant::now();
    let mut stream = response.bytes_stream();

    while let Some(item) = stream.next().await {
        if cancel_flag.load(Ordering::SeqCst) {
            let error = cancelled_download_error(task_id);
            set_chunk_status(
                chunks,
                0,
                DownloadChunkStatus::Cancelled,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }

        let bytes = match item {
            Ok(bytes) => bytes,
            Err(error) => {
                let error = make_download_error(
                    task_id,
                    "stream_failed",
                    format!("failed while reading download stream: {error}"),
                    true,
                );
                set_chunk_status(
                    chunks,
                    0,
                    DownloadChunkStatus::Failed,
                    Some(error.message.clone()),
                )
                .await;
                return Err(error);
            }
        };

        if let Err(error) = file.write_all(&bytes).await {
            let error = io_download_error(
                task_id,
                "write_failed",
                format!("failed while writing download file: {error}"),
                &error,
            );
            set_chunk_status(
                chunks,
                0,
                DownloadChunkStatus::Failed,
                Some(error.message.clone()),
            )
            .await;
            return Err(error);
        }

        downloaded_bytes += bytes.len() as u64;
        set_chunk_downloaded(chunks, 0, downloaded_bytes).await;

        if last_emit.elapsed().as_millis() >= 200 {
            emit_progress(
                app,
                task_id,
                DownloadTaskStatus::Downloading,
                response_total_bytes,
                chunks,
                started_at,
            )
            .await;
            last_emit = Instant::now();
        }
    }

    if let Err(error) = file.flush().await {
        let error = io_download_error(
            task_id,
            "flush_failed",
            format!("failed to flush download file: {error}"),
            &error,
        );
        set_chunk_status(
            chunks,
            0,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    if response_total_bytes > 0 && downloaded_bytes != response_total_bytes {
        let error = make_download_error(
            task_id,
            "file_size_mismatch",
            format!("expected {response_total_bytes} bytes but downloaded {downloaded_bytes}"),
            true,
        );
        set_chunk_status(
            chunks,
            0,
            DownloadChunkStatus::Failed,
            Some(error.message.clone()),
        )
        .await;
        return Err(error);
    }

    if response_total_bytes == 0 && downloaded_bytes > 0 {
        let mut chunks = chunks.lock().await;
        if let Some(chunk) = chunks.iter_mut().find(|chunk| chunk.index == 0) {
            chunk.end = downloaded_bytes.saturating_sub(1);
        }
    }

    set_chunk_status(chunks, 0, DownloadChunkStatus::Completed, None).await;
    emit_progress(
        app,
        task_id,
        DownloadTaskStatus::Downloading,
        response_total_bytes.max(downloaded_bytes),
        chunks,
        started_at,
    )
    .await;

    Ok(downloaded_bytes)
}

async fn remove_file_if_exists(path: &Path) -> Result<(), String> {
    match fs::remove_file(path).await {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!("failed to remove existing file: {error}")),
    }
}

async fn merge_chunk_files(
    chunk_paths: &[PathBuf],
    merge_path: &Path,
    final_path: &Path,
    task_id: &str,
    cancel_flag: CancelFlag,
) -> Result<u64, DownloadError> {
    remove_file_if_exists(merge_path)
        .await
        .map_err(|message| make_download_error(task_id, "merge_failed", message, false))?;

    let mut output = fs::File::create(merge_path).await.map_err(|error| {
        io_download_error(
            task_id,
            "merge_failed",
            format!("failed to create merged download file: {error}"),
            &error,
        )
    })?;
    let mut merged_bytes = 0;

    for chunk_path in chunk_paths {
        if cancel_flag.load(Ordering::SeqCst) {
            return Err(cancelled_download_error(task_id));
        }

        let mut input = fs::File::open(chunk_path).await.map_err(|error| {
            io_download_error(
                task_id,
                "merge_failed",
                format!("failed to open temporary chunk file: {error}"),
                &error,
            )
        })?;
        let mut buffer = vec![0_u8; 1024 * 256];

        loop {
            if cancel_flag.load(Ordering::SeqCst) {
                return Err(cancelled_download_error(task_id));
            }

            let bytes_read = input.read(&mut buffer).await.map_err(|error| {
                io_download_error(
                    task_id,
                    "merge_failed",
                    format!("failed to read temporary chunk file: {error}"),
                    &error,
                )
            })?;
            if bytes_read == 0 {
                break;
            }

            output
                .write_all(&buffer[..bytes_read])
                .await
                .map_err(|error| {
                    io_download_error(
                        task_id,
                        "merge_failed",
                        format!("failed to write merged download file: {error}"),
                        &error,
                    )
                })?;
            merged_bytes += bytes_read as u64;
        }
    }

    output.flush().await.map_err(|error| {
        io_download_error(
            task_id,
            "merge_failed",
            format!("failed to flush merged download file: {error}"),
            &error,
        )
    })?;

    remove_file_if_exists(final_path)
        .await
        .map_err(|message| make_download_error(task_id, "finalize_failed", message, false))?;
    fs::rename(merge_path, final_path)
        .await
        .map_err(|error| {
            io_download_error(
                task_id,
                "finalize_failed",
                format!("failed to move merged download into place: {error}"),
                &error,
            )
        })?;

    for chunk_path in chunk_paths {
        let _ = remove_file_if_exists(chunk_path).await;
    }

    Ok(merged_bytes)
}

async fn move_temp_file(temp_path: &Path, final_path: &Path) -> Result<(), String> {
    remove_file_if_exists(final_path).await?;
    fs::rename(temp_path, final_path)
        .await
        .map_err(|error| format!("failed to move download into place: {error}"))
}

#[tauri::command]
async fn select_directory() -> DesktopResult<String> {
    Err(not_implemented("select_directory"))
}

#[tauri::command]
async fn save_file(options: Option<SaveFileOptions>) -> DesktopResult<String> {
    if let Some(options) = options {
        let _ = options.default_name.as_deref();
    }
    Err(not_implemented("save_file"))
}

#[tauri::command]
async fn open_file(path: String) -> DesktopResult<()> {
    let _ = path;
    Err(not_implemented("open_file"))
}

#[tauri::command]
async fn open_folder(path: String) -> DesktopResult<()> {
    let _ = path;
    Err(not_implemented("open_folder"))
}

#[tauri::command]
async fn system_notification(options: SystemNotificationOptions) -> DesktopResult<()> {
    let _ = (options.title, options.body);
    Err(not_implemented("system_notification"))
}

#[tauri::command]
async fn download_task_event(payload: DownloadProgressEvent) -> DesktopResult<()> {
    let _ = (
        payload.task_id,
        payload.status,
        payload.total_bytes,
        payload.downloaded_bytes,
        payload.speed_bytes_per_second,
        payload.chunks,
    );
    Err(not_implemented("download_task_event"))
}

#[tauri::command]
async fn cancel_download_task(
    runtime: State<'_, DownloadRuntimeState>,
    task_id: String,
) -> DesktopResult<()> {
    if runtime.cancel(&task_id).await {
        Ok(())
    } else {
        Err(format!("download task {task_id} is not running"))
    }
}

#[tauri::command]
async fn start_download_task(
    app: AppHandle,
    runtime: State<'_, DownloadRuntimeState>,
    request: StartDownloadRequest,
) -> DesktopResult<DownloadTask> {
    let task_id = request
        .id
        .clone()
        .filter(|id| !id.trim().is_empty())
        .unwrap_or_else(|| format!("task-{}", current_timestamp_millis()));
    let threads = request.threads.unwrap_or(4).clamp(1, 8);
    let started_at = Instant::now();
    let created_at = current_timestamp();
    let client = Client::new();
    let probe = probe_range_support(&client, &request.source_url).await;
    let file_name = request
        .file_name
        .clone()
        .filter(|name| !name.trim().is_empty())
        .or(probe.file_name.clone())
        .or_else(|| file_name_from_url(&request.source_url))
        .or_else(|| {
            PathBuf::from(&request.save_path)
                .file_name()
                .and_then(|name| name.to_str())
                .map(str::to_string)
        })
        .unwrap_or_else(|| "download.bin".to_string());
    let final_path = resolve_final_path(&request.save_path, &file_name);

    if let Some(parent) = final_path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent)
                .await
                .map_err(|error| format!("failed to create download directory: {error}"))?;
        }
    }

    let cancel_flag = Arc::new(AtomicBool::new(false));
    runtime
        .register(task_id.clone(), cancel_flag.clone())
        .await;

    let total_bytes = probe.total_bytes.unwrap_or(0);
    let use_range = probe.supports_ranges && total_bytes > 0 && threads > 1;
    let initial_chunks = if use_range {
        split_chunks(total_bytes, threads)
    } else {
        vec![DownloadChunk {
            index: 0,
            start: 0,
            end: total_bytes.saturating_sub(1),
            downloaded_bytes: 0,
            status: DownloadChunkStatus::Queued,
            error: None,
        }]
    };
    let chunks: SharedChunks = Arc::new(Mutex::new(initial_chunks.clone()));

    emit_progress(
        &app,
        &task_id,
        DownloadTaskStatus::Downloading,
        total_bytes,
        &chunks,
        started_at,
    )
    .await;

    let download_result = if use_range {
        let mut handles = Vec::new();
        let mut chunk_paths = Vec::new();

        for chunk in initial_chunks {
            let chunk_path = temp_path_for(&final_path, &task_id, &format!("chunk{}", chunk.index));
            chunk_paths.push(chunk_path.clone());
            handles.push(tauri::async_runtime::spawn(download_range_chunk(
                client.clone(),
                app.clone(),
                task_id.clone(),
                request.source_url.clone(),
                chunk_path,
                chunk,
                total_bytes,
                chunks.clone(),
                started_at,
                cancel_flag.clone(),
            )));
        }

        let mut first_error = None;
        for handle in handles {
            match handle.await {
                Ok(Ok(())) => {}
                Ok(Err(error)) => {
                    if first_error.is_none() {
                        first_error = Some(error);
                    }
                }
                Err(error) => {
                    if first_error.is_none() {
                        first_error = Some(make_download_error(
                            &task_id,
                            "chunk_task_failed",
                            format!("chunk task failed to complete: {error}"),
                            true,
                        ));
                    }
                }
            }
        }

        if let Some(error) = first_error {
            for chunk_path in &chunk_paths {
                let _ = remove_file_if_exists(chunk_path).await;
            }
            let merge_path = temp_path_for(&final_path, &task_id, "merge");
            let _ = remove_file_if_exists(&merge_path).await;
            Err(error)
        } else {
            let merge_path = temp_path_for(&final_path, &task_id, "merge");
            match merge_chunk_files(
                &chunk_paths,
                &merge_path,
                &final_path,
                &task_id,
                cancel_flag.clone(),
            )
            .await
            {
                Ok(merged_bytes) if merged_bytes == total_bytes => Ok(merged_bytes),
                Ok(merged_bytes) => {
                    let _ = remove_file_if_exists(&final_path).await;
                    Err(make_download_error(
                        &task_id,
                        "file_size_mismatch",
                        format!("expected {total_bytes} bytes but merged {merged_bytes}"),
                        true,
                    ))
                }
                Err(error) => {
                    for chunk_path in &chunk_paths {
                        let _ = remove_file_if_exists(chunk_path).await;
                    }
                    let _ = remove_file_if_exists(&merge_path).await;
                    Err(error)
                }
            }
        }
    } else {
        let temp_path = temp_path_for(&final_path, &task_id, "single");
        let single_result = download_single_file(
            &client,
            &app,
            &task_id,
            &request.source_url,
            &temp_path,
            total_bytes,
            &chunks,
            started_at,
            cancel_flag.clone(),
        )
        .await;

        match single_result {
            Ok(downloaded_bytes) => move_temp_file(&temp_path, &final_path)
                .await
                .map(|()| downloaded_bytes)
                .map_err(|message| {
                    make_download_error(&task_id, "finalize_failed", message, false)
                }),
            Err(error) => {
                let _ = remove_file_if_exists(&temp_path).await;
                Err(error)
            }
        }
    };

    runtime.unregister(&task_id).await;

    match download_result {
        Ok(downloaded_bytes) => {
            let final_total_bytes = total_bytes.max(downloaded_bytes);
            emit_progress(
                &app,
                &task_id,
                DownloadTaskStatus::Completed,
                final_total_bytes,
                &chunks,
                started_at,
            )
            .await;

            let task = DownloadTask {
                id: task_id,
                source_url: request.source_url,
                file_name,
                save_path: final_path.to_string_lossy().to_string(),
                total_bytes: final_total_bytes,
                downloaded_bytes,
                status: DownloadTaskStatus::Completed,
                threads: if use_range { threads } else { 1 },
                created_at,
                updated_at: current_timestamp(),
                error: None,
            };

            let _ = app.emit(DOWNLOAD_COMPLETED_EVENT, &task);
            Ok(task)
        }
        Err(error) => {
            if is_cancelled_error(&error) {
                mark_incomplete_chunks(
                    &chunks,
                    DownloadChunkStatus::Cancelled,
                    Some(error.message.clone()),
                )
                .await;
                emit_progress(
                    &app,
                    &task_id,
                    DownloadTaskStatus::Cancelled,
                    total_bytes,
                    &chunks,
                    started_at,
                )
                .await;
                emit_cancelled(&app, &task_id);
                return Err(error.message);
            }

            emit_progress(
                &app,
                &task_id,
                DownloadTaskStatus::Failed,
                total_bytes,
                &chunks,
                started_at,
            )
            .await;
            emit_failed(&app, &error);
            Err(error.message)
        }
    }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            select_directory,
            save_file,
            open_file,
            open_folder,
            system_notification,
            download_task_event,
            cancel_download_task,
            start_download_task,
        ])
        .manage(DownloadRuntimeState::default())
        .run(tauri::generate_context!())
        .expect("error while running MistRelay PC Client");
}
