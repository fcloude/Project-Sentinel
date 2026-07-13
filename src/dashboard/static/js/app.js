async function updateDashboard(){

    const response = await fetch("/api/status");

    const state = await response.json();

    document.getElementById(
        "last-event"
    ).innerText = state.last_event;

}

setInterval(

    updateDashboard,

    1000

);