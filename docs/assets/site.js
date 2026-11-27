(() => {
  const root = document.documentElement;
  const themeButtons = [...document.querySelectorAll("button[data-theme-choice]")];
  const appearance = document.getElementById("appearance");
  const themeName = document.getElementById("active-theme-name");
  const metaTheme = document.getElementById("theme-color-meta");
  const names = {
    system:"System",odysseus:"Odysseus","studio-light":"Studio Light","studio-dark":"Studio Dark",
    github:"GitHub Dark",nord:"Nord",odysseas:"Odysseus Paper",ocean:"Ocean Depths",
    forest:"Forest Night",solarized:"Solarized Paper","rose-graphite":"Rose Graphite",
    ember:"Ember Studio",slate:"Slate Studio"
  };
  const themeColors = {
    odysseus:"#282c34","studio-light":"#f9f9f9","studio-dark":"#0f0f0f",github:"#0d1117",
    nord:"#2e3440",odysseas:"#edf0ec",ocean:"#101c27",forest:"#111b17",
    solarized:"#f6f2e8","rose-graphite":"#211c20",ember:"#1d1a16",slate:"#20262d"
  };
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  let choice = root.dataset.themeChoice || "system";
  if (!names[choice]) choice = "system";

  const renderTheme = () => {
    const actual = choice === "system" ? (media.matches ? "odysseus" : "studio-light") : choice;
    root.dataset.themeChoice = choice;
    root.dataset.theme = actual;
    if (themeName) themeName.textContent = names[choice];
    if (metaTheme) metaTheme.setAttribute("content", themeColors[actual]);
    themeButtons.forEach(button => {
      const selected = button.dataset.themeChoice === choice;
      button.setAttribute("aria-pressed", String(selected));
    });
  };

  const closeAppearance = () => {
    if (!appearance) return;
    appearance.open = false;
    const trigger = appearance.querySelector("summary");
    if (trigger) trigger.focus();
  };
  const saveChoice = next => {
    if (!names[next]) return;
    choice = next;
    renderTheme();
    try { localStorage.setItem("streamsnip-theme", choice); } catch (_) {}
  };
  themeButtons.forEach(button => button.addEventListener("click", () => {
    saveChoice(button.dataset.themeChoice);
    closeAppearance();
  }));
  const reset = document.getElementById("reset-theme");
  if (reset) reset.addEventListener("click", () => {
    saveChoice("system");
    closeAppearance();
  });
  if (media.addEventListener) media.addEventListener("change", () => {
    if (choice === "system") renderTheme();
  });
  renderTheme();

  document.addEventListener("click", event => {
    if (appearance && appearance.open && !appearance.contains(event.target)) appearance.open = false;
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && appearance && appearance.open) {
      appearance.open = false;
      const summary = appearance.querySelector("summary");
      if (summary) summary.focus();
    }
  });

  const menuToggle = document.getElementById("menu-toggle");
  const menu = document.getElementById("mobile-menu");
  if (menuToggle && menu) {
    const closeMenu = () => {
      menuToggle.setAttribute("aria-expanded","false");
      menuToggle.setAttribute("aria-label","Open navigation");
      menu.hidden = true;
    };
    menuToggle.addEventListener("click", () => {
      const open = menuToggle.getAttribute("aria-expanded") !== "true";
      menuToggle.setAttribute("aria-expanded",String(open));
      menuToggle.setAttribute("aria-label",open ? "Close navigation" : "Open navigation");
      menu.hidden = !open;
    });
    menu.querySelectorAll("a").forEach(link => link.addEventListener("click",closeMenu));
    document.addEventListener("keydown",event => {
      if (event.key === "Escape" && !menu.hidden) {
        closeMenu();
        menuToggle.focus();
      }
    });
    window.addEventListener("resize",() => {
      if (window.innerWidth > 900) closeMenu();
    });
  }

  // Keep the product screenshot alive only while it can be seen. The CSS animation owns each frame;
  // JavaScript only gates playback for visibility, the page tab, and the user's motion preference.
  const productMotion = document.querySelector(".product-motion");
  if (productMotion) {
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let inView = false;
    const syncProductMotion = () => {
      productMotion.classList.toggle(
        "is-motion-active",
        inView && !reducedMotion.matches && document.visibilityState === "visible"
      );
    };
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver(entries => {
        inView = entries.some(entry => entry.isIntersecting);
        syncProductMotion();
      }, { threshold: 0.15 });
      observer.observe(productMotion);
    } else {
      inView = true;
      syncProductMotion();
    }
    document.addEventListener("visibilitychange", syncProductMotion);
    if (reducedMotion.addEventListener) reducedMotion.addEventListener("change", syncProductMotion);
    else if (reducedMotion.addListener) reducedMotion.addListener(syncProductMotion);
  }
})();
