function setupUpload(){
  const input=document.getElementById('zipInput'),drop=document.getElementById('dropzone');
  document.getElementById('browse').onclick=e=>{e.stopPropagation();input.click();};
  drop.onclick=e=>{if(e.target!==input)input.click();};
  drop.onkeydown=e=>{if(e.key==='Enter')input.click();};
  input.onchange=()=>{if(input.files[0])uploadZip(input.files[0]);};
  drop.ondragover=e=>{e.preventDefault();drop.classList.add('drag');};
  drop.ondragleave=()=>drop.classList.remove('drag');
  drop.ondrop=e=>{e.preventDefault();drop.classList.remove('drag');if(e.dataTransfer.files[0])uploadZip(e.dataTransfer.files[0]);};
}
function uploadZip(file){
  if(!file.name.toLowerCase().endsWith('.zip'))return notify('Choose a ZIP archive.');
  const progress=document.getElementById('uploadProgress'),status=document.getElementById('uploadStatus');
  progress.hidden=false;progress.value=0;status.textContent=`${file.name} · ${(file.size/1048576).toFixed(2)} MB`;
  const form=new FormData();form.append('file',file);
  const xhr=new XMLHttpRequest();xhr.open('POST','/api/projects/upload');xhr.setRequestHeader('X-Studio-Request','1');
  xhr.upload.onprogress=e=>{if(e.lengthComputable)progress.value=e.loaded/e.total*100;};
  xhr.upload.onload=()=>{status.textContent='Upload complete. Validating archive and analyzing source…';progress.removeAttribute('value');};
  xhr.onerror=()=>{notify('Upload connection failed.');progress.hidden=true;};
  xhr.onload=async()=>{progress.value=100;try{const result=JSON.parse(xhr.responseText);if(xhr.status>=400)throw Error(result.detail);state.project=result.id;status.textContent='Archive validated. Source analysis complete.';await refresh();renderAnalysis();}catch(e){notify(e.message);status.textContent='Upload failed.';}};
  xhr.send(form);
}
