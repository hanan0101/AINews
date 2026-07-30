try {
      if (new URLSearchParams(window.location.search).get('restoredVersion') === '1') {
        document.documentElement.classList.add('restored-version');
        document.documentElement.classList.remove('splash-visible');
      }
    } catch (_) {}
