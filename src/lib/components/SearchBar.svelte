<script lang="ts">
  interface Props {
    onSearch: (query: string) => void;
  }

  let { onSearch }: Props = $props();
  let value = $state("");
  let timer: ReturnType<typeof setTimeout> | null = null;

  function handleInput(e: Event) {
    const target = e.target as HTMLInputElement;
    value = target.value;
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => {
      onSearch(value);
    }, 300);
  }
</script>

<div class="relative">
  <input
    type="text"
    placeholder="Search meetings..."
    {value}
    oninput={handleInput}
    style="
      width: 100%;
      padding: 10px 14px;
      border-radius: 8px;
      border: none;
      outline: none;
      background: #282826;
      color: #B0ADA5;
      font-family: 'DM Sans', sans-serif;
      font-size: 15px;
      font-weight: 400;
    "
    onfocus={(e) => {
      const el = e.target as HTMLInputElement;
      el.style.boxShadow = '0 0 0 2px rgba(168,160,120,0.20)';
    }}
    onblur={(e) => {
      const el = e.target as HTMLInputElement;
      el.style.boxShadow = 'none';
    }}
  />
</div>

<style>
  input::placeholder {
    color: #585650;
  }
</style>
