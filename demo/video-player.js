(() => {
  const initialize = () => {
    const video = document.getElementById('demo-video');
    const music = document.getElementById('demo-music');
    if (!(video instanceof HTMLVideoElement) || !(music instanceof HTMLAudioElement)) return;

    const syncThreshold = 0.12;
    let fallbackEnabled = false;

    const detectFallback = () => {
      if (typeof video.captureStream !== 'function') return false;
      const stream = video.captureStream();
      return stream.getAudioTracks().length === 0;
    };

    const syncOutput = () => {
      music.muted = video.muted;
      music.volume = video.volume;
      music.playbackRate = video.playbackRate;
    };

    const syncTime = (force = false) => {
      if (!Number.isFinite(video.currentTime)) return;
      if (force || Math.abs(music.currentTime - video.currentTime) > syncThreshold) {
        music.currentTime = video.currentTime;
      }
    };

    const playMusic = async () => {
      if (!fallbackEnabled) return;
      syncOutput();
      syncTime(true);
      try {
        await music.play();
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        console.warn('Music playback was blocked by the browser.', error);
      }
    };

    video.addEventListener('loadedmetadata', () => {
      fallbackEnabled = detectFallback();
      video.dataset.audioFallback = fallbackEnabled ? 'mp3' : 'native';
      if (!fallbackEnabled) {
        music.pause();
        music.currentTime = 0;
      }
    });
    if (video.readyState >= HTMLMediaElement.HAVE_METADATA) {
      fallbackEnabled = detectFallback();
      video.dataset.audioFallback = fallbackEnabled ? 'mp3' : 'native';
    }

    video.addEventListener('play', playMusic);
    video.addEventListener('playing', () => {
      if (fallbackEnabled && music.paused) void playMusic();
    });
    video.addEventListener('pause', () => {
      if (fallbackEnabled) music.pause();
    });
    video.addEventListener('ended', () => {
      if (!fallbackEnabled) return;
      music.pause();
      music.currentTime = 0;
    });
    video.addEventListener('waiting', () => {
      if (fallbackEnabled) music.pause();
    });
    video.addEventListener('seeking', () => {
      if (!fallbackEnabled) return;
      music.pause();
      syncTime(true);
    });
    video.addEventListener('seeked', () => {
      if (!fallbackEnabled) return;
      syncTime(true);
      if (!video.paused) void playMusic();
    });
    video.addEventListener('timeupdate', () => {
      if (!fallbackEnabled) return;
      syncTime();
      if (!video.paused && music.paused && video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) {
        void playMusic();
      }
    });
    video.addEventListener('ratechange', () => {
      if (fallbackEnabled) syncOutput();
    });
    video.addEventListener('volumechange', () => {
      if (fallbackEnabled) syncOutput();
    });

    music.addEventListener('playing', () => {
      if (fallbackEnabled) syncTime();
    });

    if (fallbackEnabled) syncOutput();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initialize, { once: true });
  } else {
    initialize();
  }
})();