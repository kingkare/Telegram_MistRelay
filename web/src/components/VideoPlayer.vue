<template>
  <div class="video-player-container">
    <video ref="videoPlayer" class="video-js vjs-big-play-centered"></video>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue';
import videojs from 'video.js';
import 'video.js/dist/video-js.css';

const props = defineProps({
  src: {
    type: String,
    required: true
  },
  type: {
    type: String,
    default: '' 
  },
  options: {
    type: Object,
    default: () => ({})
  }
});

const emit = defineEmits<{
  (e: 'ended'): void
}>();

const videoPlayer = ref<HTMLVideoElement | null>(null);
let player: any = null;

onMounted(() => {
  if (videoPlayer.value) {
    const defaultOptions = {
      controls: true,
      autoplay: true,
      preload: 'auto',
      fluid: false,
      fill: true,
      responsive: true,
      playbackRates: [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
      sources: [{
        src: props.src,
        type: props.type
      }]
    };

    player = videojs(videoPlayer.value, { ...defaultOptions, ...props.options }, () => {
      if (player) {
        player.on('ended', () => {
          emit('ended');
        });
      }
    });
  }
});

onBeforeUnmount(() => {
  if (player) {
    try {
      player.dispose();
    } catch {
      // ignore
    }
  }
});

watch(() => props.src, (newSrc) => {
  if (player && newSrc) {
    player.src({ src: newSrc, type: props.type });
    player.play();
  }
});

function toggleFullscreen() {
  if (!player) return;
  if (player.isFullscreen()) {
    player.exitFullscreen();
  } else {
    player.requestFullscreen();
  }
}

async function togglePiP() {
  try {
    if (document.pictureInPictureElement) {
      await document.exitPictureInPicture();
    } else if (player && typeof player.requestPictureInPicture === 'function') {
      await player.requestPictureInPicture();
    } else if (videoPlayer.value && typeof videoPlayer.value.requestPictureInPicture === 'function') {
      await videoPlayer.value.requestPictureInPicture();
    }
  } catch {
    // ignore if PiP not supported
  }
}

defineExpose({
  toggleFullscreen,
  togglePiP,
  getPlayer: () => player,
});
</script>

<style scoped>
.video-player-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #000000;
  position: relative;
  overflow: hidden;
}

:deep(.video-js) {
  width: 100% !important;
  height: 100% !important;
  max-width: 100%;
  max-height: 100%;
  padding-top: 0 !important;
}

:deep(.video-js video),
:deep(.video-js .vjs-tech) {
  width: 100% !important;
  height: 100% !important;
  max-height: 100% !important;
  object-fit: contain !important;
}

:deep(.video-js .vjs-big-play-button) {
  border-radius: 50%;
  width: 2.2em;
  height: 2.2em;
  line-height: 2.2em;
  margin-top: -1.1em;
  margin-left: -1.1em;
  background: rgba(255, 117, 151, 0.88);
  border: 2px solid rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(8px);
  box-shadow: 0 4px 24px rgba(255, 117, 151, 0.5);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

:deep(.video-js:hover .vjs-big-play-button) {
  background: rgba(56, 189, 248, 0.92);
  transform: scale(1.1);
  box-shadow: 0 0 32px rgba(56, 189, 248, 0.7);
}

:deep(.video-js .vjs-control-bar) {
  background: linear-gradient(180deg, transparent 0%, rgba(15, 23, 42, 0.92) 100%);
  backdrop-filter: blur(12px);
  height: 3.6em;
  padding: 0 8px;
}

:deep(.video-js .vjs-play-progress) {
  background: linear-gradient(90deg, #ff7597, #38bdf8);
}
</style>
