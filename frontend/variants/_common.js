// Shared helpers for the map-treatment variants. Loads window.BS_DATA from ../prototype_data.js
window.BSV = (function () {
  const D = window.BS_DATA || { vessels:{type:'FeatureCollection',features:[]}, cables:{type:'FeatureCollection',features:[]}, jamming:{type:'FeatureCollection',features:[]} };
  const RC = { safe:'#3FB68B', watch:'#F2B441', threat:'#F4543D' };
  const EAGLE = { name:'Eagle S', lon:24.92, lat:59.71 };
  const TRACK_A=[[28.4,59.65],[27.6,59.69],[26.7,59.72],[26.0,59.72]];
  const TRACK_GAP=[[26.0,59.72],[25.5,59.71],[25.1,59.71]];
  const TRACK_B=[[25.1,59.71],[25.0,59.71],[24.92,59.71]];

  function triImg(map, name, fill){
    const s=26,c=document.createElement('canvas');c.width=s;c.height=s;const x=c.getContext('2d');
    x.beginPath();x.moveTo(s/2,2);x.lineTo(s-5,s-4);x.lineTo(5,s-4);x.closePath();
    x.fillStyle=fill;x.fill();x.lineWidth=1.4;x.strokeStyle='rgba(11,18,32,.9)';x.stroke();
    map.addImage(name, x.getImageData(0,0,s,s));
  }
  function circle(lon,lat,km,steps){
    const pts=[];const dLat=km/110.574;const dLon=km/(111.320*Math.cos(lat*Math.PI/180));
    for(let i=0;i<=(steps||64);i++){const t=2*Math.PI*i/(steps||64);pts.push([lon+dLon*Math.cos(t),lat+dLat*Math.sin(t)]);}
    return {type:'Feature',geometry:{type:'LineString',coordinates:pts}};
  }
  function addCommon(map, opts){ // opts: {triSize, glow}
    // jamming
    map.addSource('jam',{type:'geojson',data:D.jamming});
    map.addLayer({id:'jam-f',type:'fill',source:'jam',paint:{'fill-color':'#6B7FD7','fill-opacity':opts.jamOpacity||0.10}});
    map.addLayer({id:'jam-o',type:'line',source:'jam',paint:{'line-color':'#6B7FD7','line-opacity':0.22,'line-width':0.6}});
    // cables
    map.addSource('cab',{type:'geojson',data:D.cables});
    map.addLayer({id:'cab-tel',type:'line',source:'cab',filter:['==',['get','kind'],'telecom'],paint:{'line-color':opts.telecom||'#5E6B85','line-width':1,'line-opacity':0.4}});
    map.addLayer({id:'cab-pow',type:'line',source:'cab',filter:['all',['==',['get','kind'],'power'],['!=',['get','risk'],true]],paint:{'line-color':'#7F8CA3','line-width':1.6,'line-opacity':0.6,'line-dasharray':[2,2]}});
    map.addLayer({id:'cab-rg',type:'line',source:'cab',filter:['==',['get','risk'],true],paint:{'line-color':'#F2B441','line-width':10,'line-opacity':0.16,'line-blur':4}});
    map.addLayer({id:'cab-r',type:'line',source:'cab',filter:['==',['get','risk'],true],paint:{'line-color':'#F2B441','line-width':2.6,'line-opacity':0.95}});
    // eagle track
    const aL=(id,co,p)=>{map.addSource(id,{type:'geojson',data:{type:'Feature',geometry:{type:'LineString',coordinates:co}}});map.addLayer({id:id+'L',type:'line',source:id,paint:p});};
    aL('tA',TRACK_A,{'line-color':'#F4543D','line-width':2,'line-opacity':0.7});
    aL('tGap',TRACK_GAP,{'line-color':'#8595AD','line-width':2,'line-dasharray':[1.5,2],'line-opacity':0.85});
    aL('tB',TRACK_B,{'line-color':'#F4543D','line-width':2.4,'line-opacity':0.95});
    // vessels
    triImg(map,'tri-safe',RC.safe);triImg(map,'tri-watch',RC.watch);triImg(map,'tri-threat',RC.threat);
    map.addSource('ves',{type:'geojson',data:D.vessels});
    if(opts.glow){
      map.addLayer({id:'ves-halo',type:'circle',source:'ves',filter:['!=',['get','risk'],'safe'],paint:{
        'circle-radius':['match',['get','risk'],'threat',16,10],'circle-blur':1,
        'circle-color':['match',['get','risk'],'watch',RC.watch,'threat',RC.threat,'#000'],'circle-opacity':0.30}});
    }
    map.addLayer({id:'ves',type:'symbol',source:'ves',layout:{
      'icon-image':['match',['get','risk'],'safe','tri-safe','watch','tri-watch','threat','tri-threat','tri-safe'],
      'icon-rotate':['get','course'],'icon-rotation-alignment':'map','icon-size':opts.triSize||0.6,'icon-allow-overlap':true}});
  }
  function addEagle(map, makeMarkerEl){
    const el=makeMarkerEl();el.title='Eagle S';
    new maplibregl.Marker({element:el}).setLngLat([EAGLE.lon,EAGLE.lat]).addTo(map);
    const op=document.createElement('div');op.style.cssText='display:flex;align-items:center;gap:6px;font-family:var(--mono,monospace);font-size:10px;color:#F2B441;white-space:nowrap;text-shadow:0 1px 3px #000';
    op.innerHTML='<span style="width:8px;height:8px;border-radius:50%;background:#F2B441;box-shadow:0 0 8px #F2B441"></span>Ust-Luga · departed 6d ago';
    new maplibregl.Marker({element:op,anchor:'left'}).setLngLat([28.4,59.65]).addTo(map);
    const gl=document.createElement('div');gl.style.cssText='font-family:var(--mono,monospace);font-size:10px;color:#8595AD;text-shadow:0 1px 3px #000;white-space:nowrap';gl.textContent='⚠ AIS went dark';
    new maplibregl.Marker({element:gl}).setLngLat([25.55,59.78]).addTo(map);
  }
  return { D, RC, EAGLE, triImg, circle, addCommon, addEagle };
})();
